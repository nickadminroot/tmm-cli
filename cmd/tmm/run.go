package main

import (
	"context"
	"fmt"
	"io"
	"math"
	"os"
	"os/signal"
	"sort"
	"time"

	"github.com/nickadminroot/tmm/apps/tmm-cli/internal/bundle"
	"github.com/nickadminroot/tmm/apps/tmm-cli/internal/client"
	"github.com/nickadminroot/tmm/apps/tmm-cli/internal/renderer"
)

const (
	kompasSceneOperation = "linkage-cdw-scene-plan"
	kompasPageOperation  = "linkage-cdw-page-plan"
)

func positiveFinite(value float64) bool {
	return value > 0 && !math.IsNaN(value) && !math.IsInf(value, 0)
}

func validateRunStatus(status *client.Status, runID, operation string) error {
	if status == nil || status.Version != 1 || status.RunID != runID || status.Operation != operation {
		return fmt.Errorf("server returned an unexpected run status")
	}
	return nil
}

func cancelRun(c *client.Client, runID string) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_, _ = c.CancelContext(ctx, runID)
}

// runDomain executes one free domain operation end to end and returns the exit code.
func runDomain(op string, inputPath string, outputFlag string, options map[string]any) int {
	if op == "md" {
		fmt.Fprintln(os.Stderr, "md requires MODEL.yaml and DOCUMENT.md")
		return client.ExitUsage
	}
	bundleFile := bundle.SingleFile
	if op == "linkage" {
		bundleFile = bundle.ModelFile
	}
	b, err := bundleFile(inputPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	c, cerr := client.New()
	if cerr != nil {
		fmt.Fprintln(os.Stderr, cerr)
		return client.ExitUsage
	}
	runID, uerr := bundle.NewUUIDv4()
	if uerr != nil {
		fmt.Fprintln(os.Stderr, uerr)
		return client.ExitServer
	}
	envelope := client.Envelope{
		Version:    1,
		Operation:  op,
		Entrypoint: b.Entrypoint,
		Options:    options,
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	submitted := false
	cancelSubmitted := func() {
		if submitted {
			cancelRun(c, runID)
		}
	}

	status, serr := c.SubmitContext(ctx, runID, envelope, b.Data)
	if ctx.Err() != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if serr != nil {
		return handleFailure(serr, runID, outputFlag, false)
	}
	if err := validateRunStatus(status, runID, op); err != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	submitted = true
	final, werr := c.WaitContext(ctx, runID)
	if ctx.Err() != nil {
		cancelSubmitted()
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if werr != nil {
		return handleFailure(werr, runID, outputFlag, false)
	}
	if err := validateRunStatus(final, runID, op); err != nil {
		cancelSubmitted()
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	if final.State == "cancelled" {
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitDomain
	}
	if final.State == "failed" {
		return handleTerminalDiagnostic(final.Error)
	}
	if final.State != "succeeded" || final.Result == nil {
		fmt.Fprintln(os.Stderr, "run succeeded but returned no result")
		return client.ExitServer
	}
	data, rerr := c.ResultContext(ctx, final)
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if rerr != nil {
		return handleFailure(rerr, runID, outputFlag, false)
	}
	manifest, merr := bundle.ReadManifest(data)
	if merr != nil {
		fmt.Fprintln(os.Stderr, merr)
		return client.ExitServer
	}
	if final.Result.EntryCount != len(manifest.Entries) {
		fmt.Fprintln(os.Stderr, "result entry count does not match the manifest")
		return client.ExitServer
	}
	if manifest.Operation != op {
		fmt.Fprintln(os.Stderr, "result manifest operation does not match the requested operation")
		return client.ExitServer
	}
	expectedPublication := map[string]string{"linkage": "tree", "render": "single", "svg": "single"}[op]
	if manifest.Publication != expectedPublication {
		fmt.Fprintln(os.Stderr, "result manifest publication does not match the requested operation")
		return client.ExitServer
	}
	p := bundle.Publisher{}
	switch manifest.Publication {
	case "tree":
		return finish(p.PublishTree(data, manifest, outputFlag))
	case "single":
		return finish(p.PublishSingle(data, manifest, outputFlag))
	default:
		fmt.Fprintln(os.Stderr, "result manifest publication is unsupported")
		return client.ExitServer
	}
}

// runMarkdown sends exactly the model YAML and authored Markdown bytes to the
// free preview endpoint. Scene discovery and workspace bundling are server-side.
func runMarkdown(modelPath, documentPath, paperFormat, outputPath string, sourcePath ...string) int {
	mechanism, err := readInput(modelPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	document, err := readInput(documentPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	result, err := c.RenderMarkdownContext(ctx, mechanism, document, paperFormat, sourcePath...)
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if err != nil {
		return handleLocalServerFailure(err)
	}
	if err := bundle.ReadMarkdownPreview(result, paperFormat); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	return finish((bundle.Publisher{}).PublishBytes(result, outputPath))
}

func readInput(path string) ([]byte, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("input %s: %w", path, err)
	}
	if info.IsDir() {
		return nil, fmt.Errorf("input %s is a directory", path)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("input %s: %w", path, err)
	}
	return data, nil
}

func finish(err error) int {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	return client.ExitOK
}

func handleTerminalDiagnostic(detail *client.Diagnostic) int {
	if detail == nil {
		fmt.Fprintln(os.Stderr, "Расчёт завершился без результата.")
		return client.ExitServer
	}
	printDiagnostic(detail)
	return detail.Class()
}

func printDiagnostic(detail *client.Diagnostic) {
	writeDiagnostic(os.Stderr, detail)
}

func writeDiagnostic(w io.Writer, detail *client.Diagnostic) {
	message := detail.Message
	if message == "" {
		message = "Сервер вернул ошибку расчёта."
	}
	fmt.Fprintf(w, "%s (%s)\n", message, detail.Code)
	if detail.Stage != "" {
		fmt.Fprintf(w, "Этап: %s\n", detail.Stage)
	}
	if detail.Field != "" {
		fmt.Fprintf(w, "Поле: %s\n", detail.Field)
	}
	if detail.Line > 0 || detail.Column > 0 {
		fmt.Fprintf(w, "Позиция: строка %d, столбец %d\n", detail.Line, detail.Column)
	}
	for _, step := range detail.Pipeline {
		state := map[string]string{
			"passed":  "пройден",
			"failed":  "ошибка",
			"skipped": "пропущен",
		}[step.State]
		fmt.Fprintf(w, "  [%s] %s\n", state, step.Label)
		if step.State == "failed" && step.Message != "" && step.Message != detail.Message {
			fmt.Fprintf(w, "       %s\n", step.Message)
		}
	}
}

func handleFailure(err error, runID, outputPath string, detached bool) int {
	if apiErr, ok := err.(*client.APIError); ok && apiErr.Status != 0 {
		printDiagnostic(&client.Diagnostic{
			Code:     apiErr.Code,
			Message:  apiErr.Message,
			Field:    apiErr.Field,
			Line:     apiErr.Line,
			Column:   apiErr.Column,
			Stage:    apiErr.Stage,
			Pipeline: apiErr.Pipeline,
		})
		return apiErr.Class()
	}
	if detached {
		return client.ExitInterrupted
	}
	// Transport failure after an acknowledged free submission is resumable.
	fmt.Fprintln(os.Stderr, err)
	bundle.PrintResumeLines(runID, outputPath)
	return client.ExitTransport
}

func handleLocalServerFailure(err error) int {
	if apiErr, ok := err.(*client.APIError); ok && apiErr.Status != 0 {
		printDiagnostic(&client.Diagnostic{
			Code:     apiErr.Code,
			Message:  apiErr.Message,
			Field:    apiErr.Field,
			Line:     apiErr.Line,
			Column:   apiErr.Column,
			Stage:    apiErr.Stage,
			Pipeline: apiErr.Pipeline,
		})
		return apiErr.Class()
	}
	fmt.Fprintln(os.Stderr, err)
	return client.ExitTransport
}

// runMechanisms prints only the stable mechanism balance and registry fields.
func runMechanisms() int {
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	balance, err := c.MechanismBalance()
	if err != nil {
		return handleLocalServerFailure(err)
	}
	registry, err := c.MechanismRegistry()
	if err != nil {
		return handleLocalServerFailure(err)
	}
	fmt.Printf("version: %d\nmechanisms_granted: %d\nmechanisms_used: %d\nmechanisms_reserved: %d\nmechanisms_remaining: %d\naccount_status: %s\nbilling_status: %s\n",
		balance.Version, balance.MechanismsGranted, balance.MechanismsUsed, balance.MechanismsReserved,
		balance.MechanismsRemaining, balance.AccountStatus, balance.BillingStatus)
	fmt.Printf("registry_version: %d\n", registry.Version)
	for _, item := range registry.Items {
		fmt.Printf("mechanism: %s\ndisplay_number: %d\ndescriptor_version: %d\ndescriptor_hash: %s\nbody_count: %d\nassur_group_count: %d\npolicy_digest: %s\nactivated_at: %s\n",
			item.ID, item.DisplayNumber, item.DescriptorVersion, item.DescriptorHash, item.BodyCount, item.AssurGroupCount,
			item.PolicyDigest, item.ActivatedAt.Format(time.RFC3339))
		keys := make([]string, 0, len(item.JointCounts))
		for key := range item.JointCounts {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			fmt.Printf("joint_count_%s: %d\n", key, item.JointCounts[key])
		}
		if item.LastUsedAt != nil {
			fmt.Printf("last_used_at: %s\n", item.LastUsedAt.Format(time.RFC3339))
		}
	}
	if registry.NextCursor != nil {
		fmt.Printf("next_cursor: %s\n", *registry.NextCursor)
	} else {
		fmt.Println("next_cursor:")
	}
	return client.ExitOK
}

// quoteMechanism keeps the testable, non-context API while production callers
// bind the quote request to the command cancellation context.
func quoteMechanism(c *client.Client, mechanism []byte, acceptNew bool) (bool, int) {
	return quoteMechanismContext(context.Background(), c, mechanism, acceptNew)
}

func quoteMechanismContext(ctx context.Context, c *client.Client, mechanism []byte, acceptNew bool) (bool, int) {
	return quoteMechanismContextWithFlag(ctx, c, mechanism, acceptNew, "--accept-new-mechanism")
}

func quoteMechanismContextWithFlag(
	ctx context.Context,
	c *client.Client,
	mechanism []byte,
	acceptNew bool,
	acceptanceFlag string,
) (bool, int) {
	quote, err := c.QuoteContext(ctx, mechanism)
	if err != nil {
		return false, handleLocalServerFailure(err)
	}
	if quote.Classification != "known" && quote.Classification != "new" && quote.Classification != "stock" {
		fmt.Fprintf(os.Stderr, "mechanism classification is invalid: %s\n", quote.Classification)
		return false, client.ExitServer
	}
	if quote.Balance.MechanismsRemaining < 0 || quote.Balance.MechanismsReserved < 0 ||
		(quote.Classification == "new" && !quote.RequiresCredit) ||
		((quote.Classification == "known" || quote.Classification == "stock") && quote.RequiresCredit) {
		fmt.Fprintln(os.Stderr, "mechanism quote contains an invalid balance or admission decision")
		return false, client.ExitServer
	}
	fmt.Fprintf(os.Stderr, "mechanism: %s\n", quote.Classification)
	if matchedID, ok := quote.MatchedMechanism["id"].(string); ok && matchedID != "" {
		fmt.Fprintf(os.Stderr, "matched_mechanism: %s\n", matchedID)
	}
	fmt.Fprintf(os.Stderr, "similarity: %.6f (threshold %.6f, structure %.6f, length %.6f, mass %.6f, policy_digest %s)\n",
		quote.Similarity.Score, quote.Similarity.Threshold, quote.Similarity.Structure,
		quote.Similarity.Length, quote.Similarity.Mass, quote.Similarity.PolicyDigest)
	if quote.Classification == "known" {
		if display, ok := quote.MatchedMechanism["display_number"].(float64); ok && display >= 1 {
			fmt.Fprintf(os.Stderr, "known: Механизм %.0f уже оплачен; списания не будет.\n", display)
		} else {
			fmt.Fprintln(os.Stderr, "known: Механизм уже оплачен; списания не будет.")
		}
	} else if quote.Classification == "stock" {
		fmt.Fprintln(os.Stderr, "stock: Встроенный механизм; экспорт бесплатен и в библиотеку не добавляется.")
	} else {
		before := quote.Balance.MechanismsRemaining
		after := before - 1
		fmt.Fprintf(os.Stderr, "new: score=%.6f threshold=%.6f balance before=%d after=%d\n",
			quote.Similarity.Score, quote.Similarity.Threshold, before, after)
	}
	if !quote.CanExport || (quote.RequiresCredit && quote.Balance.MechanismsRemaining < 1) {
		fmt.Fprintln(os.Stderr, "insufficient: Недостаточно механизмов. Пополните баланс и повторите команду.")
		return false, client.ExitAuth
	}
	if quote.Classification == "new" && !acceptNew {
		fmt.Fprintf(os.Stderr, "new mechanism requires %s before submission\n", acceptanceFlag)
		return false, client.ExitUsage
	}
	return quote.Classification == "new", client.ExitOK
}

func runKompasScene(modelPath, sceneName string, scale float64, acceptNew bool, outputPath string) int {
	mechanism, err := readInput(modelPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	if scale != 0 && !positiveFinite(scale) {
		fmt.Fprintln(os.Stderr, "scale must be a positive finite number")
		return client.ExitUsage
	}
	return runPaidKompas(c, mechanism, outputPath, kompasSceneOperation, acceptNew,
		func(ctx context.Context, runID, challenge string, allowNew bool) (*client.Status, error) {
			var scalePtr *float64
			if scale > 0 {
				scalePtr = &scale
			}
			return c.SubmitCDWSceneContext(ctx, runID, mechanism, sceneName, challenge, allowNew, scalePtr)
		})
}

func runKompasPage(modelPath, documentPath string, page int, paperFormat string, acceptNew bool, outputPath string) int {
	mechanism, err := readInput(modelPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	document, err := readInput(documentPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	return runPaidKompas(c, mechanism, outputPath, kompasPageOperation, acceptNew,
		func(ctx context.Context, runID, challenge string, allowNew bool) (*client.Status, error) {
			return c.SubmitCDWPageContext(ctx, runID, mechanism, document, paperFormat, challenge, allowNew, page)
		})
}

func runPaidKompas(c *client.Client, mechanism []byte, outputPath, operation string, acceptNew bool,
	submit func(context.Context, string, string, bool) (*client.Status, error)) int {
	ctx, stopSignal := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stopSignal()
	rendererClient, err := renderer.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	capabilityCtx, cancelCapability := context.WithTimeout(ctx, 30*time.Second)
	capabilities, err := rendererClient.GetCapabilitiesContext(capabilityCtx)
	cancelCapability()
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	quoteCtx, cancelQuote := context.WithTimeout(ctx, 30*time.Second)
	allowNew, quoteCode := quoteMechanismContext(quoteCtx, c, mechanism, acceptNew)
	cancelQuote()
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if quoteCode != client.ExitOK {
		return quoteCode
	}
	runID, err := bundle.NewUUIDv4()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	activated := false
	status, err := submit(ctx, runID, capabilities.Challenge, allowNew)
	if ctx.Err() != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if err != nil {
		return handlePaidFailure(err)
	}
	if err := validateRunStatus(status, runID, operation); err != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	final, err := c.WaitContext(ctx, runID)
	if ctx.Err() != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if err != nil {
		return handlePaidFailure(err)
	}
	if err := validateRunStatus(final, runID, operation); err != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	if final.State == "cancelled" {
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitDomain
	}
	if final.State == "failed" {
		return handleTerminalDiagnostic(final.Error)
	}
	if final.State != "succeeded" || final.Result == nil {
		fmt.Fprintln(os.Stderr, "paid run succeeded but returned no result")
		return client.ExitServer
	}
	activated = true
	result, err := c.ResultContext(ctx, final)
	if ctx.Err() != nil {
		return handleActivatedPaidFailure(ctx.Err())
	}
	if err != nil {
		return handleActivatedPaidFailure(err)
	}
	manifest, manifestErr := bundle.ReadManifest(result)
	if manifestErr != nil || manifest.Operation != operation || manifest.Publication != "single" ||
		final.Result.EntryCount != len(manifest.Entries) {
		if manifestErr != nil {
			return handleActivatedPaidFailure(manifestErr)
		}
		return handleActivatedPaidFailure(fmt.Errorf("result manifest does not match the paid run"))
	}
	plan, err := bundle.ReadPlan(result, operation, runID, capabilities.Challenge)
	if err != nil {
		return handleActivatedPaidFailure(err)
	}
	cdw, err := rendererClient.RenderContext(ctx, plan)
	if ctx.Err() != nil {
		if activated {
			fmt.Fprintln(os.Stderr, "Механизм уже активирован; повторное выполнение не приведёт к новому списанию.")
		}
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if err != nil {
		return handleActivatedPaidFailure(err)
	}
	return finish((bundle.Publisher{}).PublishBytes(cdw, outputPath))
}

func runXMCD(modelPath, outputPath string, allowNewMechanism bool) int {
	mechanism, err := readInput(modelPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	ctx, stopSignal := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stopSignal()
	quoteCtx, cancelQuote := context.WithTimeout(ctx, 30*time.Second)
	allowNew, quoteCode := quoteMechanismContextWithFlag(quoteCtx, c, mechanism, allowNewMechanism, "--allow-new-mechanism")
	cancelQuote()
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if quoteCode != client.ExitOK {
		return quoteCode
	}
	runID, err := bundle.NewUUIDv4()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	status, err := c.SubmitXMCDContext(ctx, runID, mechanism, allowNew)
	if ctx.Err() != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if err != nil {
		return handlePaidFailure(err)
	}
	if err := validateRunStatus(status, runID, "linkage-xmcd"); err != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	final, err := c.WaitContext(ctx, runID)
	if ctx.Err() != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitInterrupted
	}
	if err != nil {
		return handlePaidFailure(err)
	}
	if err := validateRunStatus(final, runID, "linkage-xmcd"); err != nil {
		cancelRun(c, runID)
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	if final.State == "cancelled" {
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitDomain
	}
	if final.State == "failed" {
		return handleTerminalDiagnostic(final.Error)
	}
	if final.State != "succeeded" || final.Result == nil {
		fmt.Fprintln(os.Stderr, "XMCD run succeeded but returned no result")
		return client.ExitServer
	}
	result, err := c.ResultContext(ctx, final)
	if ctx.Err() != nil {
		return handleActivatedXMCDResultFailure(ctx.Err(), runID, outputPath)
	}
	if err != nil {
		return handleActivatedXMCDResultFailure(err, runID, outputPath)
	}
	if err := publishXMCDResult(result, outputPath); err != nil {
		return handleActivatedXMCDResultFailure(err, runID, outputPath)
	}
	return client.ExitOK
}

func publishXMCDResult(result []byte, outputPath string) error {
	manifest, err := bundle.ReadManifest(result)
	if err != nil || manifest.Operation != "linkage-xmcd" || manifest.Publication != "single" ||
		len(manifest.Entries) != 1 || manifest.Entries[0].Role != "primary" ||
		manifest.Entries[0].Path != "worksheet.xmcd" {
		if err == nil {
			err = fmt.Errorf("result manifest does not contain worksheet.xmcd")
		}
		return err
	}
	return (bundle.Publisher{}).PublishSingle(result, manifest, outputPath)
}

func handleActivatedPaidFailure(err error) int {
	fmt.Fprintln(os.Stderr, "Механизм уже активирован; повторное выполнение не приведёт к новому списанию.")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
	return client.ExitServer
}
func handleActivatedXMCDResultFailure(err error, runID, outputPath string) int {
	code := handleActivatedPaidFailure(err)
	if apiErr, ok := err.(*client.APIError); !ok || apiErr.Status != 410 ||
		(apiErr.Code != "result_expired" && apiErr.Code != "result_lost") {
		printResume(runID, outputPath)
	}
	return code
}

func handlePaidFailure(err error) int {
	if apiErr, ok := err.(*client.APIError); ok && apiErr.Status != 0 {
		printDiagnostic(&client.Diagnostic{
			Code:     apiErr.Code,
			Message:  apiErr.Message,
			Field:    apiErr.Field,
			Line:     apiErr.Line,
			Column:   apiErr.Column,
			Stage:    apiErr.Stage,
			Pipeline: apiErr.Pipeline,
		})
		return apiErr.Class()
	}
	fmt.Fprintln(os.Stderr, err)
	return client.ExitTransport
}

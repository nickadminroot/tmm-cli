package main

import (
	"context"
	"fmt"
	"io"
	"math"
	"os"
	"os/signal"
	"time"

	"github.com/nickadminroot/tmm/apps/tmm-cli/internal/bundle"
	"github.com/nickadminroot/tmm/apps/tmm-cli/internal/client"
	"github.com/nickadminroot/tmm/apps/tmm-cli/internal/renderer"
)

const (
	kompasSceneOperation = "linkage-cdw-scene-plan"
	kompasPageOperation  = "linkage-cdw-page-plan"
	publicCDWScenePlan   = "cdw-scene-plan"
	publicCDWRenderPlan  = "cdw-render-plan"
)

func positiveFinite(value float64) bool {
	return value > 0 && !math.IsNaN(value) && !math.IsInf(value, 0)
}

// runDomain executes one tokenless synchronous domain operation and returns the
// exit code. The server still owns calculation and result validation; the CLI
// only publishes the validated manifest.
func runDomain(op string, inputPath string, outputFlag string, options map[string]any) int {
	if op == "md" {
		fmt.Fprintln(os.Stderr, "md requires MODEL.yaml and DOCUMENT.md")
		return client.ExitUsage
	}
	bundleFile := bundle.SingleFile
	if op == "linkage" {
		bundleFile = bundle.ModelFile
	}
	inputBundle, err := bundleFile(inputPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	envelope := client.Envelope{
		Version:    1,
		Operation:  op,
		Entrypoint: inputBundle.Entrypoint,
		Options:    options,
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	data, err := c.ComputeContext(ctx, envelope, inputBundle.Data)
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "calculation was interrupted")
		return client.ExitInterrupted
	}
	if err != nil {
		return handleLocalServerFailure(err)
	}
	manifest, err := bundle.ReadManifest(data)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
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
	publisher := bundle.Publisher{}
	switch manifest.Publication {
	case "tree":
		return finish(publisher.PublishTree(data, manifest, outputFlag))
	case "single":
		return finish(publisher.PublishSingle(data, manifest, outputFlag))
	default:
		fmt.Fprintln(os.Stderr, "result manifest publication is unsupported")
		return client.ExitServer
	}
}

// runMarkdown sends the model YAML and authored Markdown bytes to the free
// preview endpoint. Explicit local scene files are bundled when present;
// missing files remain eligible for the server's generated-catalog fallback.
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
	scenes, err := collectMarkdownScenes(documentPath, document)
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
	result, err := c.RenderMarkdownContext(ctx, mechanism, document, paperFormat, scenes, sourcePath...)
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "operation was interrupted")
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

// runResolve publishes the canonical Scene v2 document produced from one
// high-level scene JSON input through the public synchronous endpoint.
func runResolve(inputPath, outputPath string) int {
	scene, err := readInput(inputPath)
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
	renderJSON, err := c.ResolveSceneContext(ctx, scene)
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "operation was interrupted")
		return client.ExitInterrupted
	}
	if err != nil {
		if usage, ok := err.(*client.UsageError); ok {
			fmt.Fprintln(os.Stderr, usage)
			return client.ExitUsage
		}
		return handleLocalServerFailure(err)
	}
	return finish((bundle.Publisher{}).PublishBytes(renderJSON, outputPath))
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

func runKompasScene(modelPath, sceneName string, scale float64, outputPath string) int {
	mechanism, err := readInput(modelPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	if scale != 0 && !positiveFinite(scale) {
		fmt.Fprintln(os.Stderr, "scale must be a positive finite number")
		return client.ExitUsage
	}
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	return runPublicKompas(c, outputPath, []string{kompasSceneOperation}, func(ctx context.Context, challenge string) ([]byte, error) {
		var scalePtr *float64
		if scale > 0 {
			scalePtr = &scale
		}
		return c.RenderLinkageCDWSceneContext(ctx, mechanism, sceneName, challenge, scalePtr)
	})
}

func runKompasPage(modelPath, documentPath string, page int, paperFormat string, outputPath string, sourcePath ...string) int {
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
	scenes, err := collectMarkdownScenes(documentPath, document)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	optionalSourcePath := ""
	if len(sourcePath) == 1 {
		optionalSourcePath = sourcePath[0]
	}
	return runPublicKompas(c, outputPath, []string{kompasPageOperation}, func(ctx context.Context, challenge string) ([]byte, error) {
		return c.RenderLinkageCDWPageContext(ctx, mechanism, document, paperFormat, challenge, page, optionalSourcePath, scenes)
	})
}

func runKompasSceneJSON(inputPath string, scale, targetMaxSide float64, outputPath string) int {
	scene, err := readInput(inputPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	if scale != 0 && !positiveFinite(scale) {
		fmt.Fprintln(os.Stderr, "scale must be a positive finite number")
		return client.ExitUsage
	}
	if targetMaxSide != 0 && !positiveFinite(targetMaxSide) {
		fmt.Fprintln(os.Stderr, "target-max-side must be a positive finite number")
		return client.ExitUsage
	}
	if scale != 0 && targetMaxSide != 0 {
		fmt.Fprintln(os.Stderr, "scale and target-max-side are mutually exclusive")
		return client.ExitUsage
	}
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	options := map[string]any{}
	if scale != 0 {
		options["scale"] = scale
	}
	if targetMaxSide != 0 {
		options["target_max_side"] = targetMaxSide
	}
	return runPublicKompas(c, outputPath, []string{publicCDWScenePlan}, func(ctx context.Context, challenge string) ([]byte, error) {
		return c.RenderCDWSceneContext(ctx, scene, challenge, options)
	})
}

func runKompasRenderJSON(inputPath, outputPath string) int {
	renderJSON, err := readInput(inputPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	c, err := client.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitUsage
	}
	return runPublicKompas(c, outputPath, []string{publicCDWRenderPlan}, func(ctx context.Context, challenge string) ([]byte, error) {
		return c.RenderCDWRenderContext(ctx, renderJSON, challenge)
	})
}

func runPublicKompas(c *client.Client, outputPath string, operations []string,
	requestPlan func(context.Context, string) ([]byte, error)) int {
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
		fmt.Fprintln(os.Stderr, "operation was interrupted")
		return client.ExitInterrupted
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	planCtx, cancelPlan := context.WithTimeout(ctx, 15*time.Minute)
	planZIP, err := requestPlan(planCtx, capabilities.Challenge)
	cancelPlan()
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "operation was interrupted")
		return client.ExitInterrupted
	}
	if err != nil {
		if usage, ok := err.(*client.UsageError); ok {
			fmt.Fprintln(os.Stderr, usage)
			return client.ExitUsage
		}
		return handleLocalServerFailure(err)
	}
	plan, err := bundle.ReadPublicPlan(planZIP, operations, capabilities.Challenge)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	cdw, err := rendererClient.RenderContext(ctx, plan)
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "operation was interrupted")
		return client.ExitInterrupted
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	return finish((bundle.Publisher{}).PublishBytes(cdw, outputPath))
}

func runXMCD(modelPath, outputPath string) int {
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
	xmcd, err := c.GetXMCDContext(ctx, mechanism)
	if ctx.Err() != nil {
		fmt.Fprintln(os.Stderr, "operation was interrupted")
		return client.ExitInterrupted
	}
	if err != nil {
		return handleLocalServerFailure(err)
	}
	return finish((bundle.Publisher{}).PublishBytes(xmcd, outputPath))
}

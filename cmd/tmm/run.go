package main

import (
	"fmt"
	"os"
	"os/signal"

	"tmm-cli/internal/bundle"
	"tmm-cli/internal/client"
)

// runDomain executes one domain operation end to end and returns the exit code.
func runDomain(op string, inputPath string, outputFlag string, options map[string]any) int {
	var env map[string]any
	var b *bundle.Bundle
	var err error

	if op == "md" {
		format := options["format"].(string)
		env, b, err = bundle.BundleMarkdown(inputPath, format)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return client.ExitUsage
		}
	} else {
		b, err = bundle.SingleFile(inputPath, op)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return client.ExitUsage
		}
		env = map[string]any{
			"version":    1,
			"operation":  op,
			"entrypoint": b.Entrypoint,
			"options":    options,
		}
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
		Options:    env["options"],
	}

	interrupted := make(chan os.Signal, 1)
	signal.Notify(interrupted, os.Interrupt)
	detached := false
	go func() {
		<-interrupted
		detached = true
		bundle.PrintResumeLines(runID, outputFlag)
		os.Exit(client.ExitInterrupted)
	}()

	status, serr := c.Submit(runID, envelope, b.Data)
	if serr != nil {
		return handleFailure(serr, runID, outputFlag, detached)
	}
	runID = status.RunID

	final, werr := c.Wait(runID)
	if werr != nil {
		return handleFailure(werr, runID, outputFlag, detached)
	}
	if final.State == "cancelled" {
		fmt.Fprintln(os.Stderr, "run was cancelled")
		return client.ExitDomain
	}
	if final.State == "failed" {
		code := "domain_failure"
		message := ""
		if final.Error != nil {
			code = final.Error.Code
			message = final.Error.Message
		}
		fmt.Fprintf(os.Stderr, "%s (%s)\n", message, code)
		return client.ExitDomain
	}
	if final.Result == nil {
		fmt.Fprintln(os.Stderr, "run succeeded but returned no result")
		return client.ExitServer
	}

	data, rerr := c.Result(final)
	if rerr != nil {
		return handleFailure(rerr, runID, outputFlag, detached)
	}

	manifest, merr := bundle.ReadManifest(data)
	if merr != nil {
		fmt.Fprintln(os.Stderr, merr)
		return client.ExitServer
	}

	p := bundle.Publisher{}
	switch manifest.Publication {
	case "tree":
		return finish(p.PublishTree(data, manifest, outputFlag))
	case "page-set":
		return finish(p.PublishPageSet(data, manifest, outputFlag))
	default:
		return finish(p.PublishSingle(data, manifest, outputFlag))
	}
}

func finish(err error) int {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return client.ExitServer
	}
	return client.ExitOK
}

func handleFailure(err error, runID, outputPath string, detached bool) int {
	if apiErr, ok := err.(*client.APIError); ok && apiErr.Status != 0 {
		fmt.Fprintln(os.Stderr, apiErr.Error())
		return apiErr.Class()
	}
	// Transport failure after an acknowledged submission is resumable.
	fmt.Fprintln(os.Stderr, err)
	bundle.PrintResumeLines(runID, outputPath)
	return client.ExitTransport
}

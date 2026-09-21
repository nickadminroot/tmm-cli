package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"

	"github.com/nickadminroot/tmm/apps/tmm-cli/internal/bundle"
	"github.com/nickadminroot/tmm/apps/tmm-cli/internal/client"
	"github.com/spf13/cobra"
)

func main() {
	root := &cobra.Command{
		Use:   "tmm",
		Short: "TMM remote execution client",
		Long: "Thin client for the TMM remote execution service. All computation\n" +
			"happens server-side; this command sends authored inputs and publishes results.\n" +
			"Repository: https://github.com/nickadminroot/tmm-cli\n" +
			"Agent skills: https://github.com/nickadminroot/tmm-cli/tree/main/skills",
		SilenceUsage:  true,
		SilenceErrors: true,
	}

	requireOutput := func(cmd *cobra.Command) (string, error) {
		out, _ := cmd.Flags().GetString("output")
		if out == "" {
			return "", fmt.Errorf("--output is required")
		}
		return out, nil
	}
	requireInput := func(cmd *cobra.Command, args []string) (string, error) {
		if len(args) != 1 {
			return "", fmt.Errorf("exactly one INPUT is required")
		}
		return args[0], nil
	}
	addOutput := func(cmd *cobra.Command) {
		cmd.Flags().String("output", "", "output path or directory (required)")
		_ = cmd.MarkFlagRequired("output")
	}

	var scale float64
	var targetMaxSide float64
	addScaleFlags := func(cmd *cobra.Command) {
		cmd.Flags().Float64Var(&scale, "scale", 0, "explicit positive scale")
		cmd.Flags().Float64Var(&targetMaxSide, "target-max-side", 0, "target max side in mm")
		cmd.MarkFlagsMutuallyExclusive("scale", "target-max-side")
	}

	linkageCmd := &cobra.Command{
		Use:   "linkage INPUT",
		Short: "Run a linkage analysis bundle and publish the artifact tree",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			input, err := requireInput(cmd, args)
			if err != nil {
				return err
			}
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			os.Exit(runDomain("linkage", input, out, map[string]any{}))
			return nil
		},
	}
	addOutput(linkageCmd)

	xmcdCmd := &cobra.Command{
		Use:   "xmcd INPUT",
		Short: "Write the free Mathcad XMCD output for a linkage model",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			out, err := requireOutput(cmd)
			if err != nil {
				return err
			}
			if filepath.Ext(out) != ".xmcd" {
				return fmt.Errorf("--output must name a .xmcd file")
			}
			os.Exit(runXMCD(args[0], out))
			return nil
		},
	}
	addOutput(xmcdCmd)

	var mdFormat string
	var mdSourcePath string
	mdCmd := &cobra.Command{
		Use:   "md MODEL.yaml DOCUMENT.md",
		Short: "Render a Markdown document against a linkage mechanism",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			if mdFormat != "A1" && mdFormat != "A2" && mdFormat != "A3" {
				return fmt.Errorf("--format must be one of A1|A2|A3")
			}
			os.Exit(runMarkdown(args[0], args[1], mdFormat, out, mdSourcePath))
			return nil
		},
	}
	addOutput(mdCmd)
	mdCmd.Flags().StringVar(&mdFormat, "format", "", "sheet format A1|A2|A3 (required)")
	_ = mdCmd.MarkFlagRequired("format")
	mdCmd.Flags().StringVar(&mdSourcePath, "source-path", "", "logical Markdown source path")

	renderCmd := &cobra.Command{
		Use:   "render INPUT",
		Short: "Render one high-level scene JSON document",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			input, err := requireInput(cmd, args)
			if err != nil {
				return err
			}
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			options := map[string]any{}
			if cmd.Flags().Changed("scale") {
				if !positiveFinite(scale) {
					return fmt.Errorf("--scale must be a positive finite number")
				}
				options["scale"] = scale
			}
			if cmd.Flags().Changed("target-max-side") {
				if !positiveFinite(targetMaxSide) {
					return fmt.Errorf("--target-max-side must be a positive finite number")
				}
				options["target_max_side"] = targetMaxSide
			}
			if len(options) == 0 {
				return fmt.Errorf("render requires --scale or --target-max-side")
			}
			os.Exit(runDomain("render", input, out, options))
			return nil
		},
	}
	addOutput(renderCmd)
	addScaleFlags(renderCmd)

	var (
		svgFormat   string
		pixelsPerMm float64
		paddingMM   float64
		fixedStroke float64
		thinStroke  float64
		pngWidth    int
		pngHeight   int
	)
	svgCmd := &cobra.Command{
		Use:   "svg INPUT",
		Short: "Render one tmm-scene v2 JSON document to SVG or PNG bytes",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			input, err := requireInput(cmd, args)
			if err != nil {
				return err
			}
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			if cmd.Flags().Changed("scale") && !positiveFinite(scale) {
				return fmt.Errorf("--scale must be a positive finite number")
			}
			if cmd.Flags().Changed("target-max-side") && !positiveFinite(targetMaxSide) {
				return fmt.Errorf("--target-max-side must be a positive finite number")
			}
			options := map[string]any{}
			if cmd.Flags().Changed("png-width") || cmd.Flags().Changed("png-height") {
				if svgFormat != "png" {
					return fmt.Errorf("--png-width/--png-height require --format png")
				}
			}
			if svgFormat != "svg" {
				options["format"] = svgFormat
			}
			if svgFormat == "png" {
				options["width"] = pngWidth
				options["height"] = pngHeight
			}
			if scale > 0 {
				options["scale"] = scale
			}
			if targetMaxSide > 0 {
				options["target_max_side"] = targetMaxSide
			}
			if pixelsPerMm > 0 {
				options["pixels_per_mm"] = pixelsPerMm
			}
			if cmd.Flags().Changed("padding") {
				options["padding_mm"] = paddingMM
			}
			if cmd.Flags().Changed("fixed-stroke") {
				options["fixed_stroke_mm"] = fixedStroke
			}
			if cmd.Flags().Changed("thin-stroke") {
				options["thin_stroke_mm"] = thinStroke
			}
			os.Exit(runDomain("svg", input, out, options))
			return nil
		},
	}
	addOutput(svgCmd)
	addScaleFlags(svgCmd)
	svgCmd.Flags().StringVar(&svgFormat, "format", "svg", "output format svg|png")
	svgCmd.Flags().Float64Var(&pixelsPerMm, "pixels-per-mm", 18, "PNG pixels per millimeter")
	svgCmd.Flags().Float64Var(&paddingMM, "padding", 15, "SVG padding in mm")
	svgCmd.Flags().Float64Var(&fixedStroke, "fixed-stroke", 0.6, "fixed stroke width in mm")
	svgCmd.Flags().Float64Var(&thinStroke, "thin-stroke", 0.18, "thin stroke width in mm")
	svgCmd.Flags().IntVar(&pngWidth, "png-width", 1600, "PNG width in pixels")
	svgCmd.Flags().IntVar(&pngHeight, "png-height", 1200, "PNG height in pixels")

	var (
		sceneScale     float64
		sceneAcceptNew bool
		pageFormat     string
		pageNumber     int
		pageAcceptNew  bool
	)
	kompasCmd := &cobra.Command{
		Use:   "kompas",
		Short: "Create native KOMPAS drawings from linkage mechanisms",
		Args:  cobra.NoArgs,
	}
	sceneCmd := &cobra.Command{
		Use:   "scene MODEL.yaml SCENE_NAME",
		Short: "Create one linkage scene as a native KOMPAS CDW",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			if cmd.Flags().Changed("scale") && !positiveFinite(sceneScale) {
				return fmt.Errorf("--scale must be a positive finite number")
			}
			os.Exit(runKompasScene(args[0], args[1], sceneScale, sceneAcceptNew, out))
			return nil
		},
	}
	addOutput(sceneCmd)
	sceneCmd.Flags().Float64Var(&sceneScale, "scale", 0, "explicit positive scene scale")
	sceneCmd.Flags().BoolVar(&sceneAcceptNew, "accept-new-mechanism", false, "authorize one new mechanism credit")
	kompasCmd.AddCommand(sceneCmd)

	pageCmd := &cobra.Command{
		Use:   "page MODEL.yaml DOCUMENT.md",
		Short: "Create one Markdown page as a native KOMPAS CDW",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			if pageNumber < 1 {
				return fmt.Errorf("--page must be a positive page number")
			}
			if pageFormat != "A1" && pageFormat != "A2" && pageFormat != "A3" {
				return fmt.Errorf("--format must be one of A1|A2|A3")
			}
			os.Exit(runKompasPage(args[0], args[1], pageNumber, pageFormat, pageAcceptNew, out))
			return nil
		},
	}
	addOutput(pageCmd)
	pageCmd.Flags().IntVar(&pageNumber, "page", 0, "one-based page number (required)")
	_ = pageCmd.MarkFlagRequired("page")
	pageCmd.Flags().StringVar(&pageFormat, "format", "", "sheet format A1|A2|A3 (required)")
	_ = pageCmd.MarkFlagRequired("format")
	pageCmd.Flags().BoolVar(&pageAcceptNew, "accept-new-mechanism", false, "authorize one new mechanism credit")
	kompasCmd.AddCommand(pageCmd)

	mechanismsCmd := &cobra.Command{
		Use:   "mechanisms",
		Short: "Print mechanism balance and registry",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			os.Exit(runMechanisms())
			return nil
		},
	}

	resumeCmd := &cobra.Command{
		Use:   "resume UUID",
		Short: "Resume polling and publication for an acknowledged run",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			c, cerr := client.New()
			if cerr != nil {
				fmt.Fprintln(os.Stderr, cerr)
				os.Exit(client.ExitUsage)
			}
			ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
			defer stop()
			final, werr := c.WaitContext(ctx, args[0])
			if ctx.Err() != nil {
				cancelRun(c, args[0])
				fmt.Fprintln(os.Stderr, "run was cancelled")
				os.Exit(client.ExitInterrupted)
			}
			if werr != nil {
				fmt.Fprintln(os.Stderr, werr)
				if apiErr, ok := werr.(*client.APIError); ok && apiErr.Status != 0 {
					os.Exit(apiErr.Class())
				}
				printResume(args[0], out)
				os.Exit(client.ExitTransport)
			}
			if err := validateRunStatus(final, args[0], final.Operation); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(client.ExitServer)
			}
			if final.State == "succeeded" {
				if resumeErr := resumableOperationError(final.Operation); resumeErr != nil {
					fmt.Fprintln(os.Stderr, resumeErr)
					os.Exit(client.ExitDomain)
				}
				data, rerr := c.ResultContext(ctx, final)
				if rerr != nil {
					fmt.Fprintln(os.Stderr, rerr)
					os.Exit(client.ExitServer)
				}
				if final.Operation == "linkage-xmcd" {
					if xerr := publishXMCDResult(data, out); xerr != nil {
						fmt.Fprintln(os.Stderr, xerr)
						os.Exit(client.ExitServer)
					}
					os.Exit(client.ExitOK)
				}
				manifest, merr := bundle.ReadManifest(data)
				if merr != nil {
					fmt.Fprintln(os.Stderr, merr)
					os.Exit(client.ExitServer)
				}
				if final.Result.EntryCount != len(manifest.Entries) {
					fmt.Fprintln(os.Stderr, "result entry count does not match the manifest")
					os.Exit(client.ExitServer)
				}
				if manifest.Operation != final.Operation {
					fmt.Fprintln(os.Stderr, "result manifest operation does not match the run")
					os.Exit(client.ExitServer)
				}
				expectedPublication := map[string]string{"linkage": "tree", "render": "single", "svg": "single"}[final.Operation]
				if manifest.Publication != expectedPublication {
					fmt.Fprintln(os.Stderr, "result manifest publication does not match the run")
					os.Exit(client.ExitServer)
				}
				p := bundle.Publisher{}
				switch manifest.Publication {
				case "tree":
					os.Exit(finish(p.PublishTree(data, manifest, out)))
				case "page-set":
					os.Exit(finish(p.PublishPageSet(data, manifest, out)))
				case "single":
					os.Exit(finish(p.PublishSingle(data, manifest, out)))
				default:
					fmt.Fprintln(os.Stderr, "result manifest publication is unsupported")
					os.Exit(client.ExitServer)
				}
			}
			if final.State == "cancelled" {
				fmt.Fprintln(os.Stderr, "run was cancelled")
				os.Exit(client.ExitDomain)
			}
			if final.State == "failed" {
				os.Exit(handleTerminalDiagnostic(final.Error))
			}
			fmt.Fprintln(os.Stderr, "server returned an unknown run state")
			os.Exit(client.ExitServer)
			return nil
		},
	}
	resumeCmd.Flags().String("output", "", "original output path (required)")
	_ = resumeCmd.MarkFlagRequired("output")

	cancelCmd := &cobra.Command{
		Use:   "cancel UUID",
		Short: "Request cancellation of a queued or running run",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, cerr := client.New()
			if cerr != nil {
				fmt.Fprintln(os.Stderr, cerr)
				os.Exit(client.ExitUsage)
			}
			st, serr := c.Cancel(args[0])
			if serr != nil {
				fmt.Fprintln(os.Stderr, serr)
				if apiErr, ok := serr.(*client.APIError); ok {
					os.Exit(apiErr.Class())
				}
				os.Exit(client.ExitServer)
			}
			fmt.Fprintf(os.Stderr, "state: %s\n", st.State)
			return nil
		},
	}

	versionCmd := &cobra.Command{
		Use:   "version",
		Short: "Print the client version",
		RunE: func(cmd *cobra.Command, args []string) error {
			fmt.Println(client.Version)
			return nil
		},
	}

	root.AddCommand(linkageCmd, xmcdCmd, mdCmd, renderCmd, svgCmd, kompasCmd,
		mechanismsCmd, resumeCmd, cancelCmd, versionCmd)
	if err := root.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(client.ExitUsage)
	}
}

func printResume(runID, outputPath string) {
	bundle.PrintResumeLines(runID, outputPath)
}

func resumableOperationError(operation string) error {
	switch operation {
	case "linkage", "render", "svg", "linkage-xmcd":
		return nil
	case "linkage-cdw-scene-plan", "linkage-cdw-page-plan":
		return fmt.Errorf("KOMPAS CDW plans cannot be resumed; rerun the original tmm kompas command")
	default:
		return fmt.Errorf("operation %s cannot be resumed", operation)
	}
}

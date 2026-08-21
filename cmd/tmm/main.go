package main

import (
	"fmt"
	"os"

	"tmm-cli/internal/bundle"
	"tmm-cli/internal/client"

	"github.com/spf13/cobra"
)

func main() {
	root := &cobra.Command{
		Use:   "tmm",
		Short: "TMM remote execution client",
		Long: "Thin client for the TMM remote execution service. All computation\n" +
			"happens server-side; this command bundles inputs and publishes results.",
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

	var mdFormat string
	mdCmd := &cobra.Command{
		Use:   "md INPUT",
		Short: "Compile authored Markdown sheets into packed scene pages",
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
			if mdFormat != "A1" && mdFormat != "A2" && mdFormat != "A3" {
				return fmt.Errorf("--format must be one of A1|A2|A3")
			}
			os.Exit(runDomain("md", input, out, map[string]any{"format": mdFormat}))
			return nil
		},
	}
	addOutput(mdCmd)
	mdCmd.Flags().StringVar(&mdFormat, "format", "", "sheet format A1|A2|A3 (required)")
	_ = mdCmd.MarkFlagRequired("format")

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
			if scale > 0 {
				options["scale"] = scale
			}
			if targetMaxSide > 0 {
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

	kompasCmd := &cobra.Command{
		Use:   "kompas INPUT",
		Short: "Render one tmm-scene v2 document to a native KOMPAS CDW",
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
			os.Exit(runDomain("kompas", input, out, map[string]any{}))
			return nil
		},
	}
	addOutput(kompasCmd)

	quotaCmd := &cobra.Command{
		Use:   "quota",
		Short: "Print quota fields for the execution token",
		RunE: func(cmd *cobra.Command, args []string) error {
			c, cerr := client.New()
			if cerr != nil {
				fmt.Fprintln(os.Stderr, cerr)
				os.Exit(client.ExitUsage)
			}
			q, qerr := c.Quota()
			if qerr != nil {
				return qerr
			}
			fmt.Printf("run_limit: %d\nruns_used: %d\nruns_reserved: %d\nruns_remaining: %d\nexpires_at: %s\n",
				q.RunLimit, q.RunsUsed, q.RunsReserved, q.RunsRemaining, q.ExpiresAt)
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
			final, werr := c.Wait(args[0])
			if werr != nil {
				fmt.Fprintln(os.Stderr, werr)
				if apiErr, ok := werr.(*client.APIError); ok && apiErr.Status != 0 {
					os.Exit(apiErr.Class())
				}
				printResume(args[0], out)
				os.Exit(client.ExitTransport)
			}
			if final.State == "succeeded" {
				data, rerr := c.Result(final)
				if rerr != nil {
					fmt.Fprintln(os.Stderr, rerr)
					os.Exit(client.ExitServer)
				}
				manifest, merr := bundle.ReadManifest(data)
				if merr != nil {
					fmt.Fprintln(os.Stderr, merr)
					os.Exit(client.ExitServer)
				}
				p := bundle.Publisher{}
				switch manifest.Publication {
				case "tree":
					os.Exit(finish(p.PublishTree(data, manifest, out)))
				case "page-set":
					os.Exit(finish(p.PublishPageSet(data, manifest, out)))
				default:
					os.Exit(finish(p.PublishSingle(data, manifest, out)))
				}
			}
			if final.State == "cancelled" {
				fmt.Fprintln(os.Stderr, "run was cancelled")
				os.Exit(client.ExitDomain)
			}
			if final.Error != nil {
				fmt.Fprintf(os.Stderr, "%s (%s)\n", final.Error.Message, final.Error.Code)
				os.Exit(client.ExitDomain)
			}
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

	root.AddCommand(linkageCmd, mdCmd, renderCmd, svgCmd, kompasCmd,
		quotaCmd, resumeCmd, cancelCmd, versionCmd)
	if err := root.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(client.ExitUsage)
	}
}

func printResume(runID, outputPath string) {
	bundle.PrintResumeLines(runID, outputPath)
}

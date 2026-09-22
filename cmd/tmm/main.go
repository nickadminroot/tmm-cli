package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

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
			"Agent skills: https://github.com/nickadminroot/tmm-cli/tree/main/skills\n" +
			"Before each stage, install every relevant skill as a complete directory inside the current working project, read its SKILL.md, and consult it throughout the work; copying SKILL.md alone is insufficient.\n" +
			"Recommended coursework choices (select and order to match the brief):\n" +
			"Course project sections: synthesis in Mathcad/Python with metric-synthesis and mathcad-mechanisms (keep the result in XMCD); iterative physical YAML; kinematics XMCD editing; independently authored dynamics (site/CLI dynamics is alpha); analytical kinetostatics; independent gear/cam studies. Select and order what the brief requires.\n" +
			"First-semester homework: iterative YAML, kinematics, and single-position kinematics plus graphical kinetostatics sheets. Select the sections required by the assignment.\n" +
			"For a final worksheet, render every Mathcad graph and its requested Markdown/scenes in KOMPAS; keep edited Mathcad and scenes consistent.\n" +
			"Skills: https://github.com/nickadminroot/tmm-cli/tree/main/skills/tmm-cli; https://github.com/nickadminroot/tmm-cli/tree/main/skills/tmm-yaml; https://github.com/nickadminroot/tmm-cli/tree/main/skills/metric-synthesis; https://github.com/nickadminroot/tmm-cli/tree/main/skills/mathcad-mechanisms; https://github.com/nickadminroot/tmm-cli/tree/main/skills/tmm-graphics\n" +
			"Workflow: https://github.com/nickadminroot/tmm-cli/blob/main/WORKFLOW.md",
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

	resolveCmd := &cobra.Command{
		Use:     "resolve INPUT",
		Aliases: []string{"render-json"},
		Short:   "Resolve a high-level scene JSON into Scene v2 JSON (tokenless)",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			if !strings.HasSuffix(strings.ToLower(out), ".render.json") {
				return fmt.Errorf("--output must name a .render.json file")
			}
			os.Exit(runResolve(args[0], out))
			return nil
		},
	}
	addOutput(resolveCmd)

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
		sceneScale      float64
		jsonSceneScale  float64
		jsonSceneTarget float64
		pageFormat      string
		pageSourcePath  string
		pageNumber      int
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
			os.Exit(runKompasScene(args[0], args[1], sceneScale, out))
			return nil
		},
	}
	addOutput(sceneCmd)
	sceneCmd.Flags().Float64Var(&sceneScale, "scale", 0, "explicit positive scene scale")
	kompasCmd.AddCommand(sceneCmd)

	jsonSceneCmd := &cobra.Command{
		Use:   "scene-json INPUT.scene.json",
		Short: "Create a native KOMPAS CDW from arbitrary scene JSON (tokenless)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			if !strings.HasSuffix(strings.ToLower(out), ".cdw") {
				return fmt.Errorf("--output must name a .cdw file")
			}
			if cmd.Flags().Changed("scale") && !positiveFinite(jsonSceneScale) {
				return fmt.Errorf("--scale must be a positive finite number")
			}
			if cmd.Flags().Changed("target-max-side") && !positiveFinite(jsonSceneTarget) {
				return fmt.Errorf("--target-max-side must be a positive finite number")
			}
			if cmd.Flags().Changed("scale") && cmd.Flags().Changed("target-max-side") {
				return fmt.Errorf("scale and target-max-side are mutually exclusive")
			}
			os.Exit(runKompasSceneJSON(args[0], jsonSceneScale, jsonSceneTarget, out))
			return nil
		},
	}
	addOutput(jsonSceneCmd)
	jsonSceneCmd.Flags().Float64Var(&jsonSceneScale, "scale", 0, "explicit positive scene scale")
	jsonSceneCmd.Flags().Float64Var(&jsonSceneTarget, "target-max-side", 0, "target max side in mm")
	kompasCmd.AddCommand(jsonSceneCmd)

	jsonRenderCmd := &cobra.Command{
		Use:   "render-json INPUT.render.json",
		Short: "Create a native KOMPAS CDW from arbitrary Scene v2 JSON (tokenless)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			out, oerr := requireOutput(cmd)
			if oerr != nil {
				return oerr
			}
			if !strings.HasSuffix(strings.ToLower(out), ".cdw") {
				return fmt.Errorf("--output must name a .cdw file")
			}
			os.Exit(runKompasRenderJSON(args[0], out))
			return nil
		},
	}
	addOutput(jsonRenderCmd)
	kompasCmd.AddCommand(jsonRenderCmd)

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
			os.Exit(runKompasPage(args[0], args[1], pageNumber, pageFormat, out, pageSourcePath))
			return nil
		},
	}
	addOutput(pageCmd)
	pageCmd.Flags().IntVar(&pageNumber, "page", 0, "one-based page number (required)")
	_ = pageCmd.MarkFlagRequired("page")
	pageCmd.Flags().StringVar(&pageFormat, "format", "", "sheet format A1|A2|A3 (required)")
	_ = pageCmd.MarkFlagRequired("format")
	pageCmd.Flags().StringVar(&pageSourcePath, "source-path", "", "logical Markdown source path")
	kompasCmd.AddCommand(pageCmd)

	versionCmd := &cobra.Command{
		Use:   "version",
		Short: "Print the client version",
		RunE: func(cmd *cobra.Command, args []string) error {
			fmt.Println(client.Version)
			return nil
		},
	}

	root.AddCommand(linkageCmd, xmcdCmd, mdCmd, resolveCmd, renderCmd, svgCmd, kompasCmd, versionCmd)
	if err := root.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(client.ExitUsage)
	}
}

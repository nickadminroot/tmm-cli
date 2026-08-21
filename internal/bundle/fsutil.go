package bundle

import (
	"fmt"
	"os"
	"path/filepath"
)

// atomicWrite stages data to a same-directory temp file, fsyncs, and
// renames over the target. Windows uses MOVEFILE_REPLACE_EXISTING via x/sys.
func atomicWrite(target string, data []byte) error {
	dir := filepath.Dir(target)
	tmp, err := os.CreateTemp(dir, ".tmm-tmp-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer func() {
		if _, statErr := os.Stat(tmpName); statErr == nil {
			os.Remove(tmpName)
		}
	}()
	if _, werr := tmp.Write(data); werr != nil {
		tmp.Close()
		return werr
	}
	if serr := tmp.Sync(); serr != nil {
		tmp.Close()
		return serr
	}
	if cerr := tmp.Close(); cerr != nil {
		return cerr
	}
	if rerr := replaceExisting(tmpName, target); rerr != nil {
		return rerr
	}
	return nil
}

func PrintResumeLines(runID, outputPath string) {
	abs, aerr := filepath.Abs(outputPath)
	display := outputPath
	if aerr == nil {
		display = abs
	}
	escaped := escapeQuotes(display)
	fmt.Fprintf(os.Stderr, "Run ID: %s\n", runID)
	fmt.Fprintf(os.Stderr, "Resume: tmm resume %s --output \"%s\"\n", runID, escaped)
}

func escapeQuotes(path string) string {
	out := make([]byte, 0, len(path))
	for i := 0; i < len(path); i++ {
		if path[i] == '"' {
			out = append(out, '\\')
		}
		out = append(out, path[i])
	}
	return string(out)
}

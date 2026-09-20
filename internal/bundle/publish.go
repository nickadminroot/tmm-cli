package bundle

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// Publication writes a result ZIP to local disk per the publication contract.
type Publisher struct{}

// PublishBytes atomically writes one native artifact to the exact output path.
func (Publisher) PublishBytes(data []byte, outputPath string) error {
	if len(data) == 0 {
		return fmt.Errorf("empty result")
	}
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil {
		return err
	}
	if err := atomicWrite(outputPath, data); err != nil {
		return err
	}
	fmt.Println(outputPath)
	return nil
}

// publishTree atomically replaces every returned relative file under outputDir.
func (Publisher) PublishTree(zipData []byte, manifest *Manifest, outputDir string) error {
	reader, err := openZip(zipData)
	if err != nil {
		return err
	}
	if mkerr := os.MkdirAll(outputDir, 0o755); mkerr != nil {
		return mkerr
	}
	for _, entry := range manifest.Entries {
		f, ferr := reader.Open(entry.Path)
		if ferr != nil {
			return fmt.Errorf("result member %s: %w", entry.Path, ferr)
		}
		data, rerr := io.ReadAll(f)
		f.Close()
		if rerr != nil {
			return rerr
		}
		target := filepath.Join(outputDir, filepath.FromSlash(entry.Path))
		if !isUnder(outputDir, target) {
			return fmt.Errorf("member %s escapes the output directory", entry.Path)
		}
		if mkerr := os.MkdirAll(filepath.Dir(target), 0o755); mkerr != nil {
			return mkerr
		}
		if werr := atomicWrite(target, data); werr != nil {
			return werr
		}
		fmt.Println(target)
	}
	return nil
}

// publishSingle writes one member to the exact --output path.
func (Publisher) PublishSingle(zipData []byte, manifest *Manifest, outputPath string) error {
	if len(manifest.Entries) == 0 {
		return fmt.Errorf("empty result")
	}
	reader, err := openZip(zipData)
	if err != nil {
		return err
	}
	name := manifest.Entries[0].Path
	f, oerr := reader.Open(name)
	if oerr != nil {
		return oerr
	}
	data, rerr := io.ReadAll(f)
	f.Close()
	if rerr != nil {
		return rerr
	}
	dir := filepath.Dir(outputPath)
	if mkerr := os.MkdirAll(dir, 0o755); mkerr != nil {
		return mkerr
	}
	if werr := atomicWrite(outputPath, data); werr != nil {
		return werr
	}
	fmt.Println(outputPath)
	return nil
}

// publishPageSet writes page-N files and removes stale siblings only after
// all new pages are durable.
func (Publisher) PublishPageSet(zipData []byte, manifest *Manifest, outputPath string) error {
	ext := filepath.Ext(outputPath)
	stem := outputPath[:len(outputPath)-len(ext)]
	reader, err := openZip(zipData)
	if err != nil {
		return err
	}
	written := make([]string, 0, len(manifest.Entries))
	for _, entry := range manifest.Entries {
		f, oerr := reader.Open(entry.Path)
		if oerr != nil {
			return oerr
		}
		data, rerr := io.ReadAll(f)
		f.Close()
		if rerr != nil {
			return rerr
		}
		target := fmt.Sprintf("%s.page-%d%s", stem, entry.Page, ext)
		if werr := atomicWrite(target, data); werr != nil {
			return werr
		}
		written = append(written, target)
	}
	// Remove stale numbered siblings beyond the new set.
	for index := len(written) + 1; ; index++ {
		stale := fmt.Sprintf("%s.page-%d%s", stem, index, ext)
		if _, serr := os.Stat(stale); serr != nil {
			break
		}
		os.Remove(stale)
	}
	for _, path := range written {
		fmt.Println(path)
	}
	return nil
}

func openZip(zipData []byte) (*zipReader, error) {
	return newZipReader(zipData)
}

func isUnder(base, target string) bool {
	rel, err := filepath.Rel(base, target)
	if err != nil {
		return false
	}
	return rel != ".." && len(rel) > 0 && rel[:2] != ".."
}

package bundle

import (
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

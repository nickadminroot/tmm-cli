//go:build !windows

package bundle

import "os"

func replaceExisting(source, target string) error {
	// Same-directory rename is atomic on POSIX.
	return os.Rename(source, target)
}

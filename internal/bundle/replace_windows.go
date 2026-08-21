//go:build windows

package bundle

import (
	"golang.org/x/sys/windows"
)

func replaceExisting(source, target string) error {
	fromPtr, err := windows.UTF16PtrFromString(source)
	if err != nil {
		return err
	}
	toPtr, err := windows.UTF16PtrFromString(target)
	if err != nil {
		return err
	}
	return windows.MoveFileEx(fromPtr, toPtr, windows.MOVEFILE_REPLACE_EXISTING|windows.MOVEFILE_WRITE_THROUGH)
}

package bundle

import (
	"archive/zip"
	"bytes"
	"io"
)

type zipReader struct {
	reader *zip.Reader
	data   []byte
}

func newZipReader(data []byte) (*zipReader, error) {
	r, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, err
	}
	return &zipReader{reader: r, data: data}, nil
}

func (z *zipReader) Open(name string) (io.ReadCloser, error) {
	for _, f := range z.reader.File {
		if f.Name == name {
			return f.Open()
		}
	}
	return nil, io.EOF
}

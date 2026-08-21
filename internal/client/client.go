// Package client implements the tmm HTTPS transport: submit, poll, fetch.
package client

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// Version is overridden at release build time via -ldflags.
var Version = "0.1.0-dev"

// DefaultBaseURL is replaced with the production HTTPS URL in release builds.
var DefaultBaseURL = "http://127.0.0.1:8000"

// Exit code classes (see README).
const (
	ExitOK          = 0
	ExitUsage       = 2
	ExitAuth        = 3
	ExitDomain      = 4
	ExitTransport   = 5
	ExitServer      = 6
	ExitInterrupted = 130
)

// APIError is a structured error response from the service.
type APIError struct {
	Status  int
	Code    string
	Message string
}

func (e *APIError) Error() string {
	if e.Message != "" {
		return fmt.Sprintf("%s (%s)", e.Message, e.Code)
	}
	return e.Code
}

// Class maps an APIError to the stable exit-code contract.
func (e *APIError) Class() int {
	switch {
	case e.Status == 401:
		return ExitAuth
	case e.Status == 429 || e.Code == "quota_exhausted":
		return ExitAuth
	case e.Status == 409 && (e.Code == "run_not_ready" || e.Code == "run_terminal"):
		return ExitDomain
	case strings.HasPrefix(e.Code, "run_") || e.Code == "domain_failure":
		return ExitDomain
	case e.Status >= 500:
		return ExitServer
	default:
		return ExitDomain
	}
}

// Client talks to one TMM service base URL with one execution token.
type Client struct {
	BaseURL    string
	Token      string
	UserAgent  string
	HTTP       *http.Client
	RetryMax   time.Duration
	PollEvery  time.Duration
	PollBudget time.Duration
}

func New() (*Client, error) {
	base := os.Getenv("TMM_API_URL")
	if base == "" {
		base = DefaultBaseURL
	}
	parsed, err := url.Parse(base)
	if err != nil {
		return nil, usageErrorf("invalid TMM_API_URL %q: %v", base, err)
	}
	if parsed.Scheme != "https" {
		host := parsed.Hostname()
		if !isLoopback(host) {
			return nil, usageErrorf("plain HTTP is allowed only for loopback hosts; got %s", host)
		}
	}
	token := os.Getenv("TMM_API_TOKEN")
	if token == "" {
		return nil, usageErrorf("TMM_API_TOKEN is not set")
	}
	return &Client{
		BaseURL:    strings.TrimRight(base, "/"),
		Token:      token,
		UserAgent:  fmt.Sprintf("tmm-cli/%s (api/1)", Version),
		HTTP:       &http.Client{},
		RetryMax:   2 * time.Second,
		PollEvery:  500 * time.Millisecond,
		PollBudget: 15 * time.Minute,
	}, nil
}

func isLoopback(host string) bool {
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func usageErrorf(format string, args ...any) error {
	return &UsageError{msg: fmt.Sprintf(format, args...)}
}

// UsageError marks local input/argument failures (exit 2).
type UsageError struct{ msg string }

func (e *UsageError) Error() string { return e.msg }

// Envelope is the request-part JSON body.
type Envelope struct {
	Version    int         `json:"version"`
	Operation  string      `json:"operation"`
	Entrypoint string      `json:"entrypoint"`
	Options    interface{} `json:"options,omitempty"`
}

// Status mirrors the server status JSON exactly.
type Status struct {
	Version    int       `json:"version"`
	RunID      string    `json:"run_id"`
	Operation  string    `json:"operation"`
	State      string    `json:"state"`
	CreatedAt  time.Time `json:"created_at"`
	StartedAt  *time.Time
	FinishedAt *time.Time
	ExpiresAt  *time.Time
	Error      *struct {
		Code    string `json:"code"`
		Message string `json:"message"`
		Field   string `json:"field"`
	} `json:"error"`
	Result *struct {
		SHA256     string `json:"sha256"`
		Size       int64  `json:"size"`
		EntryCount int    `json:"entry_count"`
	} `json:"result"`
}

func (c *Client) newRequest(method, path string, body io.Reader) (*http.Request, error) {
	req, err := http.NewRequest(method, c.BaseURL+path, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.Token)
	req.Header.Set("User-Agent", c.UserAgent)
	return req, nil
}

func decodeError(resp *http.Response) *APIError {
	apiErr := &APIError{Status: resp.StatusCode, Code: fmt.Sprintf("http_%d", resp.StatusCode)}
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 8192))
	var payload struct {
		Detail json.RawMessage `json:"detail"`
	}
	if json.Unmarshal(data, &payload.Detail) == nil {
		var obj struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		}
		if json.Unmarshal(payload.Detail, &obj) == nil && obj.Code != "" {
			apiErr.Code = obj.Code
			apiErr.Message = obj.Message
			return apiErr
		}
		var plain string
		if json.Unmarshal(payload.Detail, &plain) == nil {
			apiErr.Message = plain
		}
	}
	if apiErr.Message == "" {
		apiErr.Message = strings.TrimSpace(string(data))
	}
	return apiErr
}

// Submit performs the idempotent PUT /v1/runs/{id} and returns the status.
func (c *Client) Submit(runID string, env Envelope, bundle []byte) (*Status, error) {
	requestPart, err := json.Marshal(env)
	if err != nil {
		return nil, err
	}
	digest := requestDigest(requestPart, bundle)

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, _ := writer.CreateFormFile("request", "request.json")
	part.Write(requestPart)
	part, _ = writer.CreateFormFile("bundle", "bundle.zip")
	part.Write(bundle)
	writer.Close()

	attempt := func() (*Status, *APIError) {
		// Recreate the body reader per attempt from identical bytes.
		var b bytes.Buffer
		w := multipart.NewWriter(&b)
		fw, _ := w.CreateFormFile("request", "request.json")
		fw.Write(requestPart)
		fw, _ = w.CreateFormFile("bundle", "bundle.zip")
		fw.Write(bundle)
		w.Close()

		req, err := c.newRequest("PUT", "/v1/runs/"+runID, bytes.NewReader(b.Bytes()))
		if err != nil {
			return nil, &APIError{Status: 0, Code: "transport", Message: err.Error()}
		}
		req.Header.Set("Content-Type", w.FormDataContentType())
		resp, err := c.HTTP.Do(req)
		if err != nil {
			return nil, &APIError{Status: 0, Code: "transport", Message: err.Error()}
		}
		defer resp.Body.Close()
		if resp.StatusCode != 202 {
			return nil, decodeError(resp)
		}
		st := &Status{}
		if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(st); err != nil {
			return nil, &APIError{Status: 0, Code: "transport", Message: err.Error()}
		}
		return st, nil
	}

	backoff := 500 * time.Millisecond
	for {
		status, apiErr := attempt()
		if apiErr == nil {
			return status, nil
		}
		if apiErr.Status != 0 { // server answered; do not retry blindly
			// A lost connection before the server persisted the run would be a
			// transport error; any real HTTP status means it was processed.
			return nil, apiErr
		}
		// Uncertain transport outcome: probe by UUID before re-PUT.
		if st, err := c.Status(runID); err == nil && st != nil {
			return st, nil
		}
		if backoff > c.RetryMax {
			return nil, fmt.Errorf("submit failed after retries; if the server accepted this run later, resume with: tmm resume %s --output <path>", runID)
		}
		time.Sleep(backoff)
		backoff *= 2
		_ = digest // reserved for future conflict diagnostics
	}
}

func requestDigest(requestPart, bundle []byte) string {
	h := sha256.New()
	h.Write(requestPart)
	h.Write([]byte{0})
	h.Write(bundle)
	return hex.EncodeToString(h.Sum(nil))
}

// Status fetches GET /v1/runs/{id}.
func (c *Client) Status(runID string) (*Status, error) {
	req, err := c.newRequest("GET", "/v1/runs/"+runID, nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, decodeError(resp)
	}
	st := &Status{}
	err = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(st)
	if err != nil {
		return nil, err
	}
	return st, nil
}

// Wait polls until a terminal state or budget exhaustion.
func (c *Client) Wait(runID string) (*Status, error) {
	deadline := time.Now().Add(c.PollBudget)
	for {
		st, err := c.Status(runID)
		if err != nil {
			if time.Now().After(deadline) {
				return nil, err
			}
			time.Sleep(c.PollEvery)
			continue
		}
		switch st.State {
		case "succeeded", "failed", "cancelled":
			return st, nil
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("timed out waiting for run %s", runID)
		}
		time.Sleep(c.PollEvery)
	}
}

// Result downloads GET /v1/runs/{id}/result and verifies size + checksum.
func (c *Client) Result(st *Status) ([]byte, error) {
	req, err := c.newRequest("GET", "/v1/runs/"+st.RunID+"/result", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, decodeError(resp)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 128<<20))
	if err != nil {
		return nil, err
	}
	if st.Result != nil {
		if int64(len(body)) != st.Result.Size {
			return nil, fmt.Errorf("result size mismatch: got %d want %d", len(body), st.Result.Size)
		}
		sum := sha256.Sum256(body)
		if hex.EncodeToString(sum[:]) != st.Result.SHA256 {
			return nil, fmt.Errorf("result checksum mismatch")
		}
	}
	return body, nil
}

// Cancel requests POST /v1/runs/{id}/cancel.
func (c *Client) Cancel(runID string) (*Status, error) {
	req, err := c.newRequest("POST", "/v1/runs/"+runID+"/cancel", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, decodeError(resp)
	}
	st := &Status{}
	err = json.NewDecoder(resp.Body).Decode(st)
	return st, err
}

// Quota prints fixed quota fields for GET /v1/quota.
type Quota struct {
	RunLimit      int    `json:"run_limit"`
	RunsUsed      int    `json:"runs_used"`
	RunsReserved  int    `json:"runs_reserved"`
	RunsRemaining int    `json:"runs_remaining"`
	ExpiresAt     string `json:"expires_at"`
}

func (c *Client) Quota() (*Quota, error) {
	req, err := c.newRequest("GET", "/v1/quota", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, decodeError(resp)
	}
	q := &Quota{}
	err = json.NewDecoder(resp.Body).Decode(q)
	return q, err
}

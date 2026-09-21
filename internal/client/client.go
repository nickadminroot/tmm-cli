// Package client implements the tmm HTTPS transport: submit, poll, fetch.
package client

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net"
	"net/http"
	"net/textproto"
	"net/url"
	"os"
	"strings"
	"time"
)

// Version is overridden at release build time via -ldflags.
var Version = "0.1.0-dev"

// DefaultBaseURL is replaced with the production HTTPS URL in release builds.
// Repository development uses the persisted URL from .tmm/dev/credentials.json.
var DefaultBaseURL = ""

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
const (
	httpRequestTimeout = 15 * time.Minute
	maxResultBytes     = 128 << 20
)

type DiagnosticStep struct {
	ID      string `json:"id"`
	Label   string `json:"label"`
	State   string `json:"state"`
	Message string `json:"message"`
}

type Diagnostic struct {
	Code     string           `json:"code"`
	Message  string           `json:"message"`
	Field    string           `json:"field"`
	Line     int              `json:"line"`
	Column   int              `json:"column"`
	Stage    string           `json:"stage"`
	Pipeline []DiagnosticStep `json:"pipeline"`
}

// APIError is a structured error response from the service.
type APIError struct {
	Status   int
	Code     string
	Message  string
	Field    string
	Line     int
	Column   int
	Stage    string
	Pipeline []DiagnosticStep
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
	case e.Status == 429 || e.Status == 402 || e.Code == "mechanism_balance_exhausted":
		return ExitAuth
	case e.Status == 409 && (e.Code == "run_not_ready" || e.Code == "run_terminal"):
		return ExitDomain
	case e.Status == 410 && (e.Code == "result_expired" || e.Code == "result_lost"):
		return ExitDomain
	case strings.HasPrefix(e.Code, "run_") || e.Code == "domain_failure":
		return ExitDomain
	case e.Status == 0:
		return ExitTransport
	case e.Status >= 500:
		return ExitServer
	default:
		return ExitDomain
	}
}

// Class maps a terminal run diagnostic to the stable exit-code contract.
func (d *Diagnostic) Class() int {
	switch d.Code {
	case "worker_failure", "worker_unavailable", "render_failure", "server_failure", "preview_render_failed":
		return ExitServer
	default:
		return ExitDomain
	}
}

// Client talks to one TMM service base URL with an execution token.
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
	return newClient(true)
}

// NewAnonymous creates a client for the public JSON scene/CDW endpoints.
// These endpoints deliberately do not accept or require a bearer token. The
// regular New constructor remains token-required for every account-scoped
// operation, so callers must opt into this transport explicitly.
func NewAnonymous() (*Client, error) {
	return newClient(false)
}

func newClient(requireToken bool) (*Client, error) {
	base := strings.TrimSpace(os.Getenv("TMM_API_URL"))
	if base == "" {
		base = strings.TrimSpace(DefaultBaseURL)
	}
	if base == "" {
		return nil, usageErrorf("TMM_API_URL is required unless this is a release build with an embedded API URL")
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
	token := ""
	if requireToken {
		token = strings.TrimSpace(os.Getenv("TMM_API_TOKEN"))
	}
	if requireToken && token == "" {
		return nil, usageErrorf("TMM_API_TOKEN is required for every API request")
	}
	return &Client{
		BaseURL:   strings.TrimRight(base, "/"),
		Token:     token,
		UserAgent: fmt.Sprintf("tmm-cli/%s (api/1)", Version),
		HTTP: &http.Client{
			Timeout: httpRequestTimeout,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
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
	Version    int         `json:"version"`
	RunID      string      `json:"run_id"`
	Operation  string      `json:"operation"`
	State      string      `json:"state"`
	CreatedAt  time.Time   `json:"created_at"`
	StartedAt  *time.Time  `json:"started_at"`
	FinishedAt *time.Time  `json:"finished_at"`
	ExpiresAt  *time.Time  `json:"expires_at"`
	Error      *Diagnostic `json:"error"`
	Result     *struct {
		SHA256     string `json:"sha256"`
		Size       int64  `json:"size"`
		EntryCount int    `json:"entry_count"`
	} `json:"result"`
}

func (c *Client) newRequest(method, path string, body io.Reader) (*http.Request, error) {
	return c.newRequestWithContext(context.Background(), method, path, body)
}

func (c *Client) newRequestWithContext(ctx context.Context, method, path string, body io.Reader) (*http.Request, error) {
	token := strings.TrimSpace(c.Token)
	if token == "" {
		return nil, usageErrorf("TMM_API_TOKEN is required for every API request")
	}
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("User-Agent", c.UserAgent)
	return req, nil
}

// newPublicRequestWithContext builds a request for an explicitly public API
// operation. It never adds Authorization, even when a caller happens to have
// a token in the environment or on a Client value.
func (c *Client) newPublicRequestWithContext(ctx context.Context, method, path string, body io.Reader) (*http.Request, error) {
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", c.UserAgent)
	return req, nil
}

func decodeError(resp *http.Response) *APIError {
	apiErr := &APIError{Status: resp.StatusCode, Code: fmt.Sprintf("http_%d", resp.StatusCode)}
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 8192))
	var payload struct {
		Detail json.RawMessage `json:"detail"`
	}
	if json.Unmarshal(data, &payload) == nil {
		var detail Diagnostic
		if json.Unmarshal(payload.Detail, &detail) == nil && detail.Code != "" {
			apiErr.Code = detail.Code
			apiErr.Message = detail.Message
			apiErr.Field = detail.Field
			apiErr.Line = detail.Line
			apiErr.Column = detail.Column
			apiErr.Stage = detail.Stage
			apiErr.Pipeline = detail.Pipeline
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
	return c.SubmitContext(context.Background(), runID, env, bundle)
}

func (c *Client) SubmitContext(ctx context.Context, runID string, env Envelope, bundle []byte) (*Status, error) {
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

		req, err := c.newRequestWithContext(ctx, "PUT", "/v1/runs/"+runID, bytes.NewReader(b.Bytes()))
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
		if st, err := c.StatusContext(ctx, runID); err == nil && st != nil {
			return st, nil
		}
		if backoff > c.RetryMax {
			return nil, fmt.Errorf("submit failed after retries; if the server accepted this run later, resume with: tmm resume %s --output <path>", runID)
		}
		timer := time.NewTimer(backoff)
		select {
		case <-ctx.Done():
			if !timer.Stop() {
				select {
				case <-timer.C:
				default:
				}
			}
			return nil, ctx.Err()
		case <-timer.C:
		}
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
	return c.StatusContext(context.Background(), runID)
}

func (c *Client) StatusContext(ctx context.Context, runID string) (*Status, error) {
	req, err := c.newRequestWithContext(ctx, "GET", "/v1/runs/"+runID, nil)
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

// Wait polls until a terminal state or budget exhaustion. A definitive
// server answer (404 run_not_found) is returned immediately.
func (c *Client) Wait(runID string) (*Status, error) {
	return c.WaitContext(context.Background(), runID)
}

func (c *Client) WaitContext(ctx context.Context, runID string) (*Status, error) {
	deadline := time.Now().Add(c.PollBudget)
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		st, err := c.StatusContext(ctx, runID)
		if err != nil {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			if apiErr, ok := err.(*APIError); ok && apiErr.Status == 404 {
				return nil, err
			}
			if time.Now().After(deadline) {
				return nil, err
			}
			if err := waitContext(ctx, c.PollEvery); err != nil {
				return nil, err
			}
			continue
		}
		switch st.State {
		case "succeeded", "failed", "cancelled":
			return st, nil
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("timed out waiting for run %s", runID)
		}
		if err := waitContext(ctx, c.PollEvery); err != nil {
			return nil, err
		}
	}
}

func waitContext(ctx context.Context, duration time.Duration) error {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

// Result downloads GET /v1/runs/{id}/result and verifies size + checksum.
func (c *Client) Result(st *Status) ([]byte, error) {
	return c.ResultContext(context.Background(), st)
}
func (c *Client) ResultContext(ctx context.Context, st *Status) ([]byte, error) {
	if st == nil || st.Result == nil || st.Result.Size < 0 || st.Result.Size > maxResultBytes ||
		len(st.Result.SHA256) != sha256.Size*2 || strings.ToLower(st.Result.SHA256) != st.Result.SHA256 {
		return nil, fmt.Errorf("result status is missing a valid size or checksum")
	}
	req, err := c.newRequestWithContext(ctx, "GET", "/v1/runs/"+st.RunID+"/result", nil)
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
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxResultBytes+1))
	if err != nil {
		return nil, err
	}
	if int64(len(body)) != st.Result.Size {
		return nil, fmt.Errorf("result size mismatch: got %d want %d", len(body), st.Result.Size)
	}
	sum := sha256.Sum256(body)
	if hex.EncodeToString(sum[:]) != st.Result.SHA256 {
		return nil, fmt.Errorf("result checksum mismatch")
	}
	return body, nil
}

// Cancel requests POST /v1/runs/{id}/cancel.
func (c *Client) Cancel(runID string) (*Status, error) {
	return c.CancelContext(context.Background(), runID)
}

func (c *Client) CancelContext(ctx context.Context, runID string) (*Status, error) {
	req, err := c.newRequestWithContext(ctx, "POST", "/v1/runs/"+runID+"/cancel", nil)
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

type MechanismBalance struct {
	Version             int    `json:"version"`
	MechanismsGranted   int    `json:"mechanisms_granted"`
	MechanismsUsed      int    `json:"mechanisms_used"`
	MechanismsReserved  int    `json:"mechanisms_reserved"`
	MechanismsRemaining int    `json:"mechanisms_remaining"`
	AccountStatus       string `json:"account_status"`
	BillingStatus       string `json:"billing_status"`
}

type MechanismRegistryItem struct {
	ID                string         `json:"id"`
	DisplayNumber     int            `json:"display_number"`
	DescriptorVersion int            `json:"descriptor_version"`
	DescriptorHash    string         `json:"descriptor_hash"`
	BodyCount         int            `json:"body_count"`
	JointCounts       map[string]int `json:"joint_counts"`
	AssurGroupCount   int            `json:"assur_group_count"`
	PolicyDigest      string         `json:"policy_digest"`
	ActivatedAt       time.Time      `json:"activated_at"`
	LastUsedAt        *time.Time     `json:"last_used_at"`
}

type MechanismRegistry struct {
	Version    int                     `json:"version"`
	Items      []MechanismRegistryItem `json:"items"`
	NextCursor *string                 `json:"next_cursor"`
}

type MechanismSimilarity struct {
	Score        float64 `json:"score"`
	Threshold    float64 `json:"threshold"`
	Structure    float64 `json:"structure"`
	Length       float64 `json:"length"`
	Mass         float64 `json:"mass"`
	PolicyDigest string  `json:"policy_digest"`
}

type MechanismQuote struct {
	Version           int                   `json:"version"`
	DescriptorVersion int                   `json:"descriptor_version"`
	SourceSHA256      string                `json:"source_sha256"`
	DescriptorHash    string                `json:"descriptor_hash"`
	Classification    string                `json:"classification"`
	MatchedMechanism  map[string]any        `json:"matched_mechanism"`
	Similarity        MechanismSimilarity   `json:"similarity"`
	RequiresCredit    bool                  `json:"requires_credit"`
	CanExport         bool                  `json:"can_export"`
	Balance           MechanismQuoteBalance `json:"balance"`
}

type MechanismQuoteBalance struct {
	MechanismsRemaining int `json:"mechanisms_remaining"`
	MechanismsReserved  int `json:"mechanisms_reserved"`
}

func (c *Client) MechanismBalance() (*MechanismBalance, error) {
	return c.MechanismBalanceContext(context.Background())
}

func (c *Client) MechanismBalanceContext(ctx context.Context) (*MechanismBalance, error) {
	req, err := c.newRequestWithContext(ctx, http.MethodGet, "/v1/mechanisms/balance", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	var balance MechanismBalance
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&balance); err != nil {
		return nil, err
	}
	return &balance, nil
}

func (c *Client) MechanismRegistry() (*MechanismRegistry, error) {
	return c.MechanismRegistryContext(context.Background())
}

func (c *Client) MechanismRegistryContext(ctx context.Context) (*MechanismRegistry, error) {
	req, err := c.newRequestWithContext(ctx, http.MethodGet, "/v1/mechanisms", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	var registry MechanismRegistry
	decoder := json.NewDecoder(io.LimitReader(resp.Body, 4<<20))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&registry); err != nil {
		return nil, err
	}
	if registry.Version != 1 {
		return nil, fmt.Errorf("mechanism registry version is unsupported")
	}
	for _, item := range registry.Items {
		if item.DescriptorVersion != 1 && item.DescriptorVersion != 2 {
			return nil, fmt.Errorf("mechanism registry descriptor version is unsupported")
		}
	}
	return &registry, nil
}

func (c *Client) Quote(yaml []byte) (*MechanismQuote, error) {
	return c.QuoteContext(context.Background(), yaml)
}

func (c *Client) QuoteContext(ctx context.Context, yaml []byte) (*MechanismQuote, error) {
	req, err := c.newRequestWithContext(ctx, http.MethodPost, "/v1/mechanisms/quote", bytes.NewReader(yaml))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/yaml")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	var quote MechanismQuote
	decoder := json.NewDecoder(io.LimitReader(resp.Body, 1<<20))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&quote); err != nil {
		return nil, err
	}
	if quote.Version != 1 || quote.DescriptorVersion != 2 {
		return nil, fmt.Errorf("mechanism quote version is unsupported")
	}
	return &quote, nil
}

// GetXMCD requests the free native Mathcad worksheet output for one authored
// linkage YAML document. The server performs the linkage solve and returns the
// XMCD bytes directly; no run admission, quote, or balance mutation is used.
func (c *Client) GetXMCD(yaml []byte) ([]byte, error) {
	return c.GetXMCDContext(context.Background(), yaml)
}

func (c *Client) GetXMCDContext(ctx context.Context, yaml []byte) ([]byte, error) {
	req, err := c.newRequestWithContext(ctx, http.MethodPost, "/v1/linkage/xmcd", bytes.NewReader(yaml))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/yaml")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	contentType := strings.ToLower(strings.TrimSpace(strings.Split(resp.Header.Get("Content-Type"), ";")[0]))
	if contentType != "application/x-mathcad+xml" {
		return nil, fmt.Errorf("server returned an unsupported XMCD content type")
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxResultBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) == 0 || int64(len(data)) > maxResultBytes {
		return nil, fmt.Errorf("server returned an invalid XMCD size")
	}
	return data, nil
}

// ResolveScene resolves a high-level scene JSON document into the canonical
// Scene v2 (.render.json) document. The endpoint is intentionally public and
// does not require an account token.
func (c *Client) ResolveScene(scene []byte) ([]byte, error) {
	return c.ResolveSceneContext(context.Background(), scene)
}

func (c *Client) ResolveSceneContext(ctx context.Context, scene []byte) ([]byte, error) {
	return c.postPublicJSONContext(ctx, "/v1/scenes/resolve", scene, maxResultBytes)
}

// RenderCDWScene requests a signed native-renderer plan from a high-level
// scene JSON document. The caller sends the returned bytes to the local
// KOMPAS Renderer; no account token is used for this public endpoint.
func (c *Client) RenderCDWScene(scene []byte) ([]byte, error) {
	return c.RenderCDWSceneContext(context.Background(), scene, "", nil)
}

func (c *Client) RenderCDWSceneContext(ctx context.Context, scene []byte, challenge string, options map[string]any) ([]byte, error) {
	return c.postPublicPlanContext(ctx, "/v1/cdw/scene", "scene", scene, challenge, options)
}

// RenderCDWRender requests a signed native-renderer plan from a resolved
// Scene v2 (.render.json) document. The endpoint is public and tokenless.
func (c *Client) RenderCDWRender(renderJSON []byte) ([]byte, error) {
	return c.RenderCDWRenderContext(context.Background(), renderJSON, "")
}

func (c *Client) RenderCDWRenderContext(ctx context.Context, renderJSON []byte, challenge string) ([]byte, error) {
	return c.postPublicPlanContext(ctx, "/v1/cdw/render", "render", renderJSON, challenge, nil)
}

func (c *Client) postPublicJSONContext(ctx context.Context, path string, input []byte, maxBytes int64) ([]byte, error) {
	if len(input) == 0 || int64(len(input)) > maxResultBytes {
		return nil, usageErrorf("JSON input size is invalid")
	}
	var document any
	if err := json.Unmarshal(input, &document); err != nil {
		return nil, usageErrorf("JSON input is invalid: %v", err)
	}
	if object, ok := document.(map[string]any); !ok || object == nil {
		return nil, usageErrorf("JSON input root must be an object")
	}
	req, err := c.newPublicRequestWithContext(ctx, http.MethodPost, path, bytes.NewReader(input))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	contentType := strings.ToLower(strings.TrimSpace(strings.Split(resp.Header.Get("Content-Type"), ";")[0]))
	if contentType != "application/json" && !strings.HasSuffix(contentType, "+json") {
		return nil, fmt.Errorf("server returned an unsupported JSON content type")
	}
	if maxBytes <= 0 || maxBytes > maxResultBytes {
		maxBytes = maxResultBytes
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) == 0 || int64(len(data)) > maxBytes {
		return nil, fmt.Errorf("server returned an invalid JSON size")
	}
	var response any
	if err := json.Unmarshal(data, &response); err != nil {
		return nil, fmt.Errorf("server returned invalid JSON: %w", err)
	}
	if object, ok := response.(map[string]any); !ok || object == nil {
		return nil, fmt.Errorf("server returned a non-object JSON document")
	}
	return data, nil
}

func (c *Client) postPublicPlanContext(
	ctx context.Context,
	path, inputField string,
	input []byte,
	challenge string,
	options map[string]any,
) ([]byte, error) {
	if len(input) == 0 || int64(len(input)) > maxResultBytes {
		return nil, usageErrorf("JSON input size is invalid")
	}
	var document any
	if err := json.Unmarshal(input, &document); err != nil {
		return nil, usageErrorf("JSON input is invalid: %v", err)
	}
	if object, ok := document.(map[string]any); !ok || object == nil {
		return nil, usageErrorf("JSON input root must be an object")
	}
	if strings.TrimSpace(challenge) == "" {
		return nil, usageErrorf("renderer challenge is required")
	}
	requestOptions := map[string]any{"version": 1, "agent_challenge": challenge}
	for key, value := range options {
		requestOptions[key] = value
	}
	envelope := map[string]any{
		inputField: json.RawMessage(input),
		"options":  requestOptions,
	}
	body, err := json.Marshal(envelope)
	if err != nil {
		return nil, err
	}
	req, err := c.newPublicRequestWithContext(ctx, http.MethodPost, path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	contentType := strings.ToLower(strings.TrimSpace(strings.Split(resp.Header.Get("Content-Type"), ";")[0]))
	if contentType != "application/zip" && contentType != "application/octet-stream" {
		return nil, fmt.Errorf("server returned an unsupported KOMPAS plan content type")
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxResultBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) == 0 || int64(len(data)) > maxResultBytes {
		return nil, fmt.Errorf("server returned an invalid KOMPAS plan size")
	}
	return data, nil
}

type multipartPart struct {
	name        string
	filename    string
	contentType string
	data        []byte
}

func makeMultipart(parts ...multipartPart) ([]byte, string, error) {
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	for _, part := range parts {
		header := make(textproto.MIMEHeader)
		disposition := fmt.Sprintf(`form-data; name="%s"; filename="%s"`, part.name, part.filename)
		header.Set("Content-Disposition", disposition)
		header.Set("Content-Type", part.contentType)
		target, err := writer.CreatePart(header)
		if err != nil {
			return nil, "", err
		}
		if _, err := target.Write(part.data); err != nil {
			return nil, "", err
		}
	}
	if err := writer.Close(); err != nil {
		return nil, "", err
	}
	return body.Bytes(), writer.FormDataContentType(), nil
}

// validateScenesPayload keeps the optional scenes part a JSON object whose
// values are JSON objects. The server still owns Scene v2/high-level schema
// validation; this check protects the multipart contract and avoids silently
// uploading arrays, scalars, or null values under scene keys.
func validateScenesPayload(data []byte) error {
	var scenes map[string]json.RawMessage
	if err := json.Unmarshal(data, &scenes); err != nil {
		return fmt.Errorf("scenes payload must be a JSON object: %w", err)
	}
	if scenes == nil {
		return fmt.Errorf("scenes payload must be a JSON object")
	}
	for name, raw := range scenes {
		if name == "" {
			return fmt.Errorf("scenes payload contains an empty scene path")
		}
		var object map[string]json.RawMessage
		if err := json.Unmarshal(raw, &object); err != nil || object == nil {
			return fmt.Errorf("scene %q must be a JSON object", name)
		}
	}
	return nil
}

func (c *Client) RenderMarkdown(mechanism, document []byte, format string) ([]byte, error) {
	return c.RenderMarkdownContext(context.Background(), mechanism, document, format, nil)
}

// RenderMarkdownContext posts the authored mechanism, Markdown document, and
// optional local scene object. When scenes is nil the server keeps its normal
// generated-catalog fallback. sourcePath contains at most one logical Markdown
// path used to resolve relative scene keys.
func (c *Client) RenderMarkdownContext(ctx context.Context, mechanism, document []byte, format string, scenes []byte, sourcePath ...string) ([]byte, error) {
	options := map[string]string{"format": format}
	if len(sourcePath) > 1 {
		return nil, fmt.Errorf("markdown source path specified more than once")
	}
	if len(sourcePath) == 1 && sourcePath[0] != "" {
		options["source_path"] = sourcePath[0]
	}
	optionsJSON, err := json.Marshal(options)
	if err != nil {
		return nil, err
	}
	parts := []multipartPart{
		{name: "mechanism", filename: "mechanism.yaml", contentType: "application/yaml", data: mechanism},
		{name: "document", filename: "document.md", contentType: "text/markdown", data: document},
	}
	if scenes != nil {
		if err := validateScenesPayload(scenes); err != nil {
			return nil, err
		}
		parts = append(parts, multipartPart{name: "scenes", filename: "scenes.json", contentType: "application/json", data: scenes})
	}
	parts = append(parts, multipartPart{name: "options", filename: "options.json", contentType: "application/json", data: optionsJSON})
	body, contentType, err := makeMultipart(parts...)
	if err != nil {
		return nil, err
	}
	req, err := c.newRequestWithContext(ctx, http.MethodPost, "/v1/linkage/markdown/render", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", contentType)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusMultiStatus {
		return nil, decodeError(resp)
	}
	result, err := io.ReadAll(io.LimitReader(resp.Body, 32<<20+1))
	if err != nil {
		return nil, err
	}
	if len(result) > 32<<20 {
		return nil, fmt.Errorf("markdown result exceeds 32 MiB")
	}
	return result, nil
}

func (c *Client) SubmitCDWScene(runID string, mechanism []byte, sceneName, challenge string, acceptNew bool, scale *float64) (*Status, error) {
	return c.SubmitCDWSceneContext(context.Background(), runID, mechanism, sceneName, challenge, acceptNew, scale)
}

func (c *Client) SubmitCDWSceneContext(ctx context.Context, runID string, mechanism []byte, sceneName, challenge string, acceptNew bool, scale *float64) (*Status, error) {
	options := map[string]any{
		"version":             1,
		"agent_challenge":     challenge,
		"allow_new_mechanism": acceptNew,
		"scene_name":          sceneName,
	}
	if scale != nil {
		options["scale"] = *scale
	}
	return c.submitCDWContext(ctx, "/v1/linkage/cdw/scenes/"+runID, runID, mechanism, nil, options, nil)
}

func (c *Client) SubmitCDWPage(runID string, mechanism, document []byte, format, challenge string, acceptNew bool, page int) (*Status, error) {
	return c.SubmitCDWPageContext(context.Background(), runID, mechanism, document, format, challenge, acceptNew, page, "", nil)
}

// SubmitCDWPageContext submits one Markdown page and optional local scenes.
// sourcePath is the logical Markdown path used by the server for scene
// resolution; an empty path keeps the server's input/document.md default.
func (c *Client) SubmitCDWPageContext(ctx context.Context, runID string, mechanism, document []byte, format, challenge string, acceptNew bool, page int, sourcePath string, scenes []byte) (*Status, error) {
	options := map[string]any{
		"version":             1,
		"agent_challenge":     challenge,
		"allow_new_mechanism": acceptNew,
		"format":              format,
		"page":                page,
	}
	if sourcePath != "" {
		options["source_path"] = sourcePath
	}
	return c.submitCDWContext(ctx, "/v1/linkage/cdw/pages/"+runID, runID, mechanism, document, options, scenes)
}

type xmcdOptions struct {
	Version           int  `json:"version"`
	AllowNewMechanism bool `json:"allow_new_mechanism"`
}

func (c *Client) SubmitXMCD(runID string, mechanism []byte, allowNew bool) (*Status, error) {
	return c.SubmitXMCDContext(context.Background(), runID, mechanism, allowNew)
}

func (c *Client) SubmitXMCDContext(ctx context.Context, runID string, mechanism []byte, allowNew bool) (*Status, error) {
	options, err := json.Marshal(xmcdOptions{Version: 1, AllowNewMechanism: allowNew})
	if err != nil {
		return nil, err
	}
	body, contentType, err := makeMultipart(
		multipartPart{name: "mechanism", filename: "mechanism.yaml", contentType: "application/yaml", data: mechanism},
		multipartPart{name: "options", filename: "options.json", contentType: "application/json", data: options},
	)
	if err != nil {
		return nil, err
	}
	status, err := c.submitPaidMultipartContext(
		ctx,
		"/v1/linkage/xmcd/"+runID,
		runID,
		body,
		contentType,
	)
	if err != nil {
		return nil, err
	}
	if status.RunID != runID || status.Operation != "linkage-xmcd" {
		return nil, fmt.Errorf("server returned an unexpected XMCD run status")
	}
	return status, nil
}

func (c *Client) submitCDWContext(ctx context.Context, path, runID string, mechanism, document []byte, options map[string]any, scenes []byte) (*Status, error) {
	optionsJSON, err := json.Marshal(options)
	if err != nil {
		return nil, err
	}
	parts := []multipartPart{
		{name: "mechanism", filename: "mechanism.yaml", contentType: "application/yaml", data: mechanism},
	}
	if document != nil {
		parts = append(parts, multipartPart{name: "document", filename: "document.md", contentType: "text/markdown", data: document})
	}
	if scenes != nil {
		if err := validateScenesPayload(scenes); err != nil {
			return nil, err
		}
		parts = append(parts, multipartPart{name: "scenes", filename: "scenes.json", contentType: "application/json", data: scenes})
	}
	parts = append(parts, multipartPart{name: "options", filename: "options.json", contentType: "application/json", data: optionsJSON})
	body, contentType, err := makeMultipart(parts...)
	if err != nil {
		return nil, err
	}
	return c.submitPaidMultipartContext(ctx, path, runID, body, contentType)
}

func (c *Client) submitPaidMultipartContext(ctx context.Context, path, runID string, body []byte, contentType string) (*Status, error) {
	attempt := func() (*Status, error) {
		req, reqErr := c.newRequestWithContext(ctx, http.MethodPut, path, bytes.NewReader(body))
		if reqErr != nil {
			return nil, reqErr
		}
		req.Header.Set("Content-Type", contentType)
		resp, doErr := c.HTTP.Do(req)
		if doErr != nil {
			return nil, doErr
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusAccepted {
			return nil, decodeError(resp)
		}
		var status Status
		if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&status); err != nil {
			return nil, err
		}
		return &status, nil
	}
	backoff := 500 * time.Millisecond
	for {
		status, err := attempt()
		if err == nil {
			return status, nil
		}
		if apiErr, ok := err.(*APIError); ok && apiErr.Status != 0 {
			return nil, apiErr
		}
		if status, statusErr := c.StatusContext(ctx, runID); statusErr == nil {
			return status, nil
		}
		if backoff > c.RetryMax {
			return nil, fmt.Errorf("paid submission failed after retries: %w", err)
		}
		if err := waitContext(ctx, backoff); err != nil {
			return nil, err
		}
		backoff *= 2
	}
}

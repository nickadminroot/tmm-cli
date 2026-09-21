// Package client implements the tokenless TMM HTTPS transport.
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

// Client talks to one TMM service base URL. Calculation and rendering routes
// are public synchronous endpoints; no account token is ever attached.
type Client struct {
	BaseURL   string
	UserAgent string
	HTTP      *http.Client
}

func New() (*Client, error) {
	return newClient()
}

func newClient() (*Client, error) {
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
	return &Client{
		BaseURL:   strings.TrimRight(base, "/"),
		UserAgent: fmt.Sprintf("tmm-cli/%s (api/1)", Version),
		HTTP: &http.Client{
			Timeout: httpRequestTimeout,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
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

func (c *Client) newRequestWithContext(ctx context.Context, method, path string, body io.Reader) (*http.Request, error) {
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

// Compute executes one tokenless calculation synchronously and returns its
// validated result ZIP. The server owns the solver and result manifest; the
// client verifies the transport checksum before publication.
func (c *Client) Compute(env Envelope, inputBundle []byte) ([]byte, error) {
	return c.ComputeContext(context.Background(), env, inputBundle)
}

func (c *Client) ComputeContext(ctx context.Context, env Envelope, inputBundle []byte) ([]byte, error) {
	requestPart, err := json.Marshal(env)
	if err != nil {
		return nil, err
	}
	if len(inputBundle) == 0 || int64(len(inputBundle)) > maxResultBytes {
		return nil, usageErrorf("calculation bundle size is invalid")
	}
	body, contentType, err := makeMultipart(
		multipartPart{name: "request", filename: "request.json", contentType: "application/json", data: requestPart},
		multipartPart{name: "bundle", filename: "bundle.zip", contentType: "application/zip", data: inputBundle},
	)
	if err != nil {
		return nil, err
	}
	req, err := c.newRequestWithContext(ctx, http.MethodPost, "/v1/compute", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", contentType)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	responseType := strings.ToLower(strings.TrimSpace(strings.Split(resp.Header.Get("Content-Type"), ";")[0]))
	if responseType != "application/zip" {
		return nil, fmt.Errorf("server returned an unsupported calculation result content type")
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxResultBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) == 0 || int64(len(data)) > maxResultBytes {
		return nil, fmt.Errorf("server returned an invalid calculation result size")
	}
	expected := strings.TrimSpace(resp.Header.Get("X-Result-Sha256"))
	if len(expected) != sha256.Size*2 || strings.ToLower(expected) != expected {
		return nil, fmt.Errorf("server returned an invalid calculation result checksum")
	}
	if _, err := hex.DecodeString(expected); err != nil {
		return nil, fmt.Errorf("server returned an invalid calculation result checksum")
	}
	sum := sha256.Sum256(data)
	if hex.EncodeToString(sum[:]) != expected {
		return nil, fmt.Errorf("calculation result checksum mismatch")
	}
	return data, nil
}

// GetXMCD requests the public native Mathcad worksheet output for one authored
// linkage YAML document. The server performs the linkage solve and returns the
// XMCD bytes directly.
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
// Scene v2 (.render.json) document through the public tokenless endpoint.
func (c *Client) ResolveScene(scene []byte) ([]byte, error) {
	return c.ResolveSceneContext(context.Background(), scene)
}

func (c *Client) ResolveSceneContext(ctx context.Context, scene []byte) ([]byte, error) {
	return c.postPublicJSONContext(ctx, "/v1/scenes/resolve", scene, maxResultBytes)
}

// RenderCDWScene requests a signed native-renderer plan from a high-level
// scene JSON document. The caller sends the returned bytes to the local
// KOMPAS Renderer; this public endpoint is tokenless.
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
	req, err := c.newRequestWithContext(ctx, http.MethodPost, path, bytes.NewReader(input))
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
	req, err := c.newRequestWithContext(ctx, http.MethodPost, path, bytes.NewReader(body))
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

// RenderLinkageCDWScene requests a signed KOMPAS plan for one generated
// linkage scene. It is synchronous and tokenless; the local renderer verifies
// the plan signature and challenge binding before creating the CDW.
func (c *Client) RenderLinkageCDWScene(mechanism []byte, sceneName, challenge string, scale *float64) ([]byte, error) {
	return c.RenderLinkageCDWSceneContext(context.Background(), mechanism, sceneName, challenge, scale)
}

func (c *Client) RenderLinkageCDWSceneContext(ctx context.Context, mechanism []byte, sceneName, challenge string, scale *float64) ([]byte, error) {
	options := map[string]any{
		"version":         1,
		"scene_name":      sceneName,
		"agent_challenge": challenge,
	}
	if scale != nil {
		options["scale"] = *scale
	}
	return c.postLinkagePlanContext(ctx, "/v1/linkage/cdw/scene", mechanism, nil, nil, options)
}

// RenderLinkageCDWPage requests a signed KOMPAS plan for one Markdown page.
// Explicit local scenes are uploaded under their canonical directive keys.
func (c *Client) RenderLinkageCDWPage(
	mechanism, document []byte,
	format, challenge string,
	page int,
	sourcePath string,
	scenes []byte,
) ([]byte, error) {
	return c.RenderLinkageCDWPageContext(context.Background(), mechanism, document, format, challenge, page, sourcePath, scenes)
}

func (c *Client) RenderLinkageCDWPageContext(
	ctx context.Context,
	mechanism, document []byte,
	format, challenge string,
	page int,
	sourcePath string,
	scenes []byte,
) ([]byte, error) {
	options := map[string]any{
		"version":         1,
		"format":          format,
		"page":            page,
		"agent_challenge": challenge,
	}
	if sourcePath != "" {
		options["source_path"] = sourcePath
	}
	return c.postLinkagePlanContext(ctx, "/v1/linkage/cdw/page", mechanism, document, scenes, options)
}

func (c *Client) postLinkagePlanContext(
	ctx context.Context,
	path string,
	mechanism, document, scenes []byte,
	options map[string]any,
) ([]byte, error) {
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
	req, err := c.newRequestWithContext(ctx, http.MethodPost, path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", contentType)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	responseType := strings.ToLower(strings.TrimSpace(strings.Split(resp.Header.Get("Content-Type"), ";")[0]))
	if responseType != "application/zip" {
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

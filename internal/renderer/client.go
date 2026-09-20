// Package renderer implements the localhost KOMPAS Renderer transport.
package renderer

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	DefaultURL      = "http://127.0.0.1:17342"
	ProtocolVersion = 2
	MaxPlanBytes    = 8 << 20
	MaxCDWBytes     = 25 << 20
)

var requiredCapabilities = [...]string{
	"scene-v2",
	"api7",
	"api5-text",
	"visible-document",
	"cdw-return",
}

// Error is a structured response from the local renderer.
type Error struct {
	Status  int
	Code    string
	Message string
}

func (e *Error) Error() string {
	if e.Message == "" {
		return e.Code
	}
	return fmt.Sprintf("%s (%s)", e.Message, e.Code)
}

// Capabilities is the short-lived challenge used to bind a plan to one renderer.
type Capabilities struct {
	Version         int      `json:"version"`
	RendererID      string   `json:"agent_id"`
	RendererVersion string   `json:"agent_version"`
	Challenge       string   `json:"challenge"`
	Capabilities    []string `json:"capabilities"`
}

// Client talks to a loopback-only renderer without carrying the TMM bearer token.
type Client struct {
	BaseURL   string
	UserAgent string
	HTTP      *http.Client
}

func New() (*Client, error) {
	base := os.Getenv("TMM_KOMPAS_RENDERER_URL")
	if base == "" {
		base = DefaultURL
	}
	parsed, err := url.Parse(base)
	if err != nil {
		return nil, fmt.Errorf("invalid TMM_KOMPAS_RENDERER_URL %q: %w", base, err)
	}
	if parsed.Scheme != "http" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, fmt.Errorf("KOMPAS Renderer URL must be plain HTTP without credentials or query")
	}
	if parsed.Path != "" && parsed.Path != "/" {
		return nil, fmt.Errorf("KOMPAS Renderer URL must not contain a path")
	}
	if !isLoopback(parsed.Hostname()) {
		return nil, fmt.Errorf("KOMPAS Renderer URL must use a loopback host")
	}
	if port := parsed.Port(); port != "" {
		value, parseErr := strconv.Atoi(port)
		if parseErr != nil || value < 1 || value > 65535 {
			return nil, fmt.Errorf("KOMPAS Renderer URL has an invalid port")
		}
	} else {
		return nil, fmt.Errorf("KOMPAS Renderer URL must include an explicit port")
	}
	return &Client{
		BaseURL:   strings.TrimRight(base, "/"),
		UserAgent: "tmm-cli-kompas-renderer/1",
		HTTP: &http.Client{
			Timeout: 15 * time.Minute,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}, nil
}

func isLoopback(host string) bool {
	return host == "localhost" || host == "127.0.0.1"
}

func (c *Client) request(method, path string, body io.Reader) (*http.Request, error) {
	return c.requestWithContext(context.Background(), method, path, body)
}

func (c *Client) requestWithContext(ctx context.Context, method, path string, body io.Reader) (*http.Request, error) {
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", c.UserAgent)
	req.Header.Set("X-TMM-Agent-Request", "1")
	return req, nil
}

func decodeError(resp *http.Response) *Error {
	result := &Error{Status: resp.StatusCode, Code: fmt.Sprintf("agent_http_%d", resp.StatusCode)}
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	var payload struct {
		Error struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if json.Unmarshal(data, &payload) == nil && payload.Error.Code != "" {
		result.Code = payload.Error.Code
		result.Message = payload.Error.Message
		return result
	}
	result.Message = strings.TrimSpace(string(data))
	return result
}

// GetCapabilities obtains a fresh renderer challenge.
func (c *Client) GetCapabilities() (*Capabilities, error) {
	return c.GetCapabilitiesContext(context.Background())
}

// GetCapabilitiesContext obtains a fresh renderer challenge with cancellation.
func (c *Client) GetCapabilitiesContext(ctx context.Context) (*Capabilities, error) {
	req, err := c.requestWithContext(ctx, http.MethodGet, "/v1/capabilities", nil)
	if err != nil {
		return nil, &Error{Code: "agent_transport", Message: err.Error()}
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, &Error{Code: "agent_unavailable", Message: err.Error()}
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	var capabilities Capabilities
	if err := json.NewDecoder(io.LimitReader(resp.Body, 64<<10)).Decode(&capabilities); err != nil {
		return nil, &Error{Code: "agent_protocol", Message: "invalid capabilities response"}
	}
	contentType := strings.ToLower(strings.SplitN(resp.Header.Get("Content-Type"), ";", 2)[0])
	if contentType != "application/json" {
		return nil, &Error{Code: "agent_protocol", Message: "invalid capabilities content type"}
	}
	if capabilities.Version != ProtocolVersion ||
		!validUUID(capabilities.RendererID) ||
		!validRendererVersion(capabilities.RendererVersion) ||
		!validChallenge(capabilities.Challenge) ||
		!hasRequiredCapabilities(capabilities.Capabilities) {
		return nil, &Error{
			Code:    "agent_incompatible",
			Message: "renderer does not support the required protocol v2 capabilities",
		}
	}
	return &capabilities, nil
}

func validRendererVersion(value string) bool {
	if len(value) < 1 || len(value) > 64 {
		return false
	}
	for _, character := range value {
		if character <= 0x1f || character == 0x7f {
			return false
		}
	}
	return true
}

func validCapability(value string) bool {
	if len(value) < 1 || len(value) > 64 {
		return false
	}
	for _, character := range value {
		if !((character >= 'a' && character <= 'z') ||
			(character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') ||
			character == '_' || character == '.' || character == '-') {
			return false
		}
	}
	return true
}

func hasRequiredCapabilities(capabilities []string) bool {
	if len(capabilities) > 32 {
		return false
	}
	available := make(map[string]struct{}, len(capabilities))
	for _, capability := range capabilities {
		if !validCapability(capability) {
			return false
		}
		if _, duplicate := available[capability]; duplicate {
			return false
		}
		available[capability] = struct{}{}
	}
	for _, required := range requiredCapabilities {
		if _, ok := available[required]; !ok {
			return false
		}
	}
	return true
}

func validChallenge(value string) bool {
	if len(value) != 43 {
		return false
	}
	decoded, err := base64.RawURLEncoding.DecodeString(value)
	return err == nil && len(decoded) == 32
}

func validUUID(value string) bool {
	if len(value) != 36 {
		return false
	}
	for index := range value {
		if index == 8 || index == 13 || index == 18 || index == 23 {
			if value[index] != '-' {
				return false
			}
			continue
		}
		if !strings.ContainsRune("0123456789abcdefABCDEF", rune(value[index])) {
			return false
		}
	}
	raw, err := hex.DecodeString(strings.ReplaceAll(value, "-", ""))
	if err != nil {
		return false
	}
	return raw[6]&0xf0 == 0x40 && raw[8]&0xc0 == 0x80
}

// Render sends a signed plan and returns the raw CDW bytes.
func (c *Client) Render(plan []byte) ([]byte, error) {
	return c.RenderContext(context.Background(), plan)
}

func (c *Client) RenderContext(ctx context.Context, plan []byte) ([]byte, error) {
	if len(plan) == 0 || len(plan) > MaxPlanBytes {
		return nil, &Error{Code: "plan_invalid", Message: "plan size is invalid"}
	}
	req, err := c.requestWithContext(ctx, http.MethodPost, "/v1/render", bytes.NewReader(plan))
	if err != nil {
		return nil, &Error{Code: "agent_transport", Message: err.Error()}
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, &Error{Code: "agent_unavailable", Message: err.Error()}
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, decodeError(resp)
	}
	contentType := strings.ToLower(strings.SplitN(resp.Header.Get("Content-Type"), ";", 2)[0])
	if contentType != "application/octet-stream" {
		return nil, &Error{Code: "agent_protocol", Message: "invalid drawing content type"}
	}
	disposition := strings.TrimSpace(strings.SplitN(resp.Header.Get("Content-Disposition"), ";", 2)[0])
	if !strings.EqualFold(disposition, "attachment") {
		return nil, &Error{Code: "agent_protocol", Message: "invalid drawing content disposition"}
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, MaxCDWBytes+1))
	if err != nil {
		return nil, &Error{Code: "agent_protocol", Message: "failed to read drawing"}
	}
	if len(data) == 0 || len(data) > MaxCDWBytes {
		return nil, &Error{Code: "agent_protocol", Message: "drawing size is invalid"}
	}
	expected := strings.TrimSpace(resp.Header.Get("X-TMM-Result-Sha256"))
	if expected == "" {
		return nil, &Error{Code: "agent_protocol", Message: "drawing checksum is missing"}
	}
	expectedSum, err := hex.DecodeString(expected)
	if err != nil || len(expectedSum) != sha256.Size {
		return nil, &Error{Code: "agent_protocol", Message: "drawing checksum is invalid"}
	}
	sum := sha256.Sum256(data)
	if !bytes.Equal(expectedSum, sum[:]) {
		return nil, &Error{Code: "agent_protocol", Message: "drawing checksum mismatch"}
	}
	return data, nil
}

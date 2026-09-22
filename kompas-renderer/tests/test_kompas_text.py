"""Unit tests for tmm_scene_kompas.kompas_text — AST and parser."""

import unittest

from tmm_scene_kompas.kompas_text import (
    Decorated,
    Fraction,
    LatexParser,
    Radical,
    Script,
    StyledNode,
    Sequence,
    Text,
    UnderOver,
    count_primes,
    compile_kompas_control_string,
    compile_latex_api5_exact,
    compile_unicode_text,
    contains_math_unicode,
    parse_latex_document,
    parse_latex_string,
    plain_node_text,
    plain_text,
)


# ─── Basic text ──────────────────────────────────────────────────────────────


class TestApi5ExactScripts(unittest.TestCase):
    def test_nested_script_does_not_leak_kompas_delimiters(self):
        plan = compile_latex_api5_exact(r"M_{\Phi_{3}}")
        content = plan.lines[0].items[0].content
        self.assertEqual(content, "M$;^(Symbol type A)+70~3$")
        self.assertNotIn("$;3$$", content)

    def test_regular_script_remains_structurally_intact(self):
        plan = compile_latex_api5_exact(r"F_{21}^{\tau}")
        self.assertEqual(
            plan.lines[0].items[0].content,
            "F$^(Symbol type A)+116~;21$",
        )




class TestKompasControlString(unittest.TestCase):
    def test_existing_ast_lowering_produces_native_cell_control_syntax(self):
        self.assertEqual(compile_kompas_control_string(r"l_1"), "l$;1$")
        self.assertEqual(
            compile_kompas_control_string(r"F_{32}^{\tau}"),
            "F$^(Symbol type A)+116~;32$",
        )
        self.assertEqual(compile_kompas_control_string(r"\frac{a}{b}"), "$da;b$")
        self.assertEqual(compile_kompas_control_string(r"\sqrt{x}"), "@+98~$(x)$")
        self.assertNotIn(r"\\frac", compile_kompas_control_string(r"\frac{a}{b}"))

    def test_plain_control_lowering_preserves_markdown_unescaped_cell_text(self):
        self.assertEqual(compile_kompas_control_string("A | B"), "A | B")


class TestSemanticSymbols(unittest.TestCase):
    def test_parser_matches_svg_semantic_glyphs(self):
        self.assertEqual(parse_latex_string(r"\triangle"), Text("△"))
        self.assertEqual(parse_latex_string(r"\sim"), Text("∼"))

    def test_native_consumers_preserve_semantic_glyphs(self):
        source = r"\triangle bc\ldots\sim\triangle BC\ldots"
        expected = "△ bc…∼△ BC…"
        self.assertEqual(compile_kompas_control_string(source), expected)
        plan = compile_latex_api5_exact(source)
        self.assertEqual(
            "".join(item.content for item in plan.lines[0].items), expected
        )

    def test_unicode_semantic_glyphs_select_native_api5_path(self):
        self.assertTrue(contains_math_unicode("△∼"))
        plan = compile_unicode_text("△∼")
        self.assertEqual([item.content for item in plan.lines[0].items], ["△", "∼"])


class TestText(unittest.TestCase):
    def test_plain_char(self):
        node = parse_latex_string("a")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "a")

    def test_multiple_chars(self):
        node = parse_latex_string("abc")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "abc")

    def test_special_chars(self):
        node = parse_latex_string("a+b=c")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "a+b=c")

    def test_numbers(self):
        node = parse_latex_string("123")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "123")


# ─── Groups ──────────────────────────────────────────────────────────────────


class TestGroups(unittest.TestCase):
    def test_simple_group(self):
        node = parse_latex_string("{abc}")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "abc")

    def test_nested_group(self):
        node = parse_latex_string("{a{b}c}")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "abc")

    def test_empty_group(self):
        node = parse_latex_string("{}")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "")

    def test_unclosed_group_raises_valueerror(self):
        with self.assertRaises(ValueError) as ctx:
            parse_latex_string("{abc")
        self.assertIn("Unclosed group", str(ctx.exception))
        self.assertIn("position", str(ctx.exception))

    def test_unclosed_group_after_content(self):
        with self.assertRaises(ValueError) as ctx:
            parse_latex_string("a{b{c}d")
        self.assertIn("Unclosed group", str(ctx.exception))
        self.assertIn("position", str(ctx.exception))


# ─── Subscript and superscript ──────────────────────────────────────────────


class TestSubscriptSuperscript(unittest.TestCase):
    def test_subscript_single_char(self):
        node = parse_latex_string("a_1")
        self.assertIsInstance(node, Script)
        self.assertIsInstance(node.base, Text)
        self.assertEqual(node.base.value, "a")
        self.assertIsNone(node.superscript)
        self.assertIsNotNone(node.subscript)
        self.assertEqual(plain_text(node.subscript), "1")

    def test_superscript_single_char(self):
        node = parse_latex_string("a^2")
        self.assertIsInstance(node, Script)
        self.assertEqual(node.base.value, "a")
        self.assertIsNotNone(node.superscript)
        self.assertEqual(plain_text(node.superscript), "2")
        self.assertIsNone(node.subscript)

    def test_both_subscript_and_superscript(self):
        node = parse_latex_string("a_1^2")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.base), "a")
        self.assertEqual(plain_text(node.subscript), "1")
        self.assertEqual(plain_text(node.superscript), "2")

    def test_grouped_subscript(self):
        node = parse_latex_string("a_{123}")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.subscript), "123")

    def test_grouped_superscript(self):
        node = parse_latex_string("a^{xyz}")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.superscript), "xyz")

    def test_F_tau_script(self):
        """F_{32}^{\\tau} → Script(base=F, superscript=τ, subscript=32)"""
        node = parse_latex_string("F_{32}^{\\tau}")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.base), "F")
        self.assertEqual(plain_text(node.subscript), "32")
        self.assertEqual(plain_text(node.superscript), "τ")

    def test_superscript_then_subscript(self):
        node = parse_latex_string("a^2_1")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.base), "a")
        self.assertEqual(plain_text(node.superscript), "2")
        self.assertEqual(plain_text(node.subscript), "1")

    def test_subscript_with_command(self):
        node = parse_latex_string("a_{\\alpha}")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.subscript), "α")

    def test_superscript_with_command(self):
        node = parse_latex_string("a^{\\beta}")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.superscript), "β")

    def test_multiple_scripts_not_allowed(self):
        # Only the last ^ and _ are kept; the parser overwrites
        # with the last occurrence of each.
        node = parse_latex_string("a_1_2")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.subscript), "2")

    def test_empty_superscript(self):
        node = parse_latex_string("a^")
        # After consuming ^, parse_script_arg at EOF returns Text("")
        self.assertIsInstance(node, Script)
        self.assertIsNotNone(node.superscript)
        self.assertEqual(plain_text(node.superscript), "")


# ─── Fraction ────────────────────────────────────────────────────────────────


class TestFraction(unittest.TestCase):
    def test_simple_fraction(self):
        node = parse_latex_string("\\frac{1}{2}")
        self.assertIsInstance(node, Fraction)
        self.assertEqual(plain_text(node.numerator), "1")
        self.assertEqual(plain_text(node.denominator), "2")

    def test_fraction_with_chars(self):
        node = parse_latex_string("\\frac{a}{b}")
        self.assertIsInstance(node, Fraction)

    def test_fraction_with_scripts_in_numerator(self):
        node = parse_latex_string("\\frac{x^2}{y}")
        self.assertIsInstance(node, Fraction)
        self.assertIsInstance(node.numerator, Script)
        self.assertEqual(plain_text(node.numerator), "x^(2)")

    def test_nested_fraction(self):
        node = parse_latex_string("\\frac{\\frac{a}{b}}{c}")
        self.assertIsInstance(node, Fraction)
        self.assertIsInstance(node.numerator, Fraction)

    def test_missing_numerator_brace_raises(self):
        with self.assertRaises(ValueError) as ctx:
            parse_latex_string("\\frac 1{2}")
        self.assertIn("position", str(ctx.exception))

    def test_unclosed_fraction_raises(self):
        with self.assertRaises(ValueError) as ctx:
            parse_latex_string("\\frac{1}{2")
        self.assertIn("Unclosed group", str(ctx.exception))

    def test_sqrt_group(self):
        self.assertIsInstance(parse_latex_string("\\sqrt{x}"), Radical)

    def test_mathrm_bare_atom_is_transparent(self):
        node = parse_latex_string("\\mathrm I")
        self.assertIsInstance(node, Text)
        self.assertEqual(plain_text(node), "I")


# ─── Decorations (overline, underline, vec) ──────────────────────────────────


class TestDecorations(unittest.TestCase):
    def test_overline(self):
        node = parse_latex_string("\\overline{ABC}")
        self.assertIsInstance(node, Decorated)
        self.assertEqual(node.kind, "overline")
        self.assertEqual(plain_text(node.body), "ABC")

    def test_widehat_uses_editable_overline_special(self):
        node = parse_latex_string("\\widehat{ABC}")
        self.assertIsInstance(node, Decorated)
        self.assertEqual(node.kind, "overline")
        self.assertEqual(plain_text(node.body), "ABC")
        items = compile_latex_api5_exact(r"\widehat{ABC}").lines[0].items
        self.assertEqual([item.i_s_numb for item in items], [95, 0])

    def test_vec(self):
        node = parse_latex_string("\\vec{v}")
        self.assertIsInstance(node, Decorated)
        self.assertEqual(node.kind, "overline")
        self.assertEqual(plain_text(node.body), "v")

    def test_vec_bare_atom(self):
        node = parse_latex_string("\\vec F_{42}")
        self.assertIsInstance(node, Script)
        self.assertIsInstance(node.base, Decorated)
        self.assertEqual(plain_text(node.base.body), "F")
        self.assertEqual(plain_text(node.subscript), "42")

    def test_vec_bare_greek_command(self):
        node = parse_latex_string("\\vec \\Phi_{5}")
        self.assertIsInstance(node, Script)
        self.assertIsInstance(node.base, Decorated)
        self.assertEqual(plain_text(node.base.body), "Φ")
        self.assertEqual(plain_text(node.subscript), "5")

    def test_overline_bare_atom(self):
        node = parse_latex_string("\\overline F_{42}")
        self.assertIsInstance(node, Script)
        self.assertIsInstance(node.base, Decorated)
        self.assertEqual(plain_text(node.base.body), "F")
        self.assertEqual(plain_text(node.subscript), "42")

    def test_bar(self):
        node = parse_latex_string("\\bar{x}")
        self.assertIsInstance(node, Decorated)
        self.assertEqual(node.kind, "overline")

    def test_vct_alias(self):
        node = parse_latex_string("\\vct{F}")
        self.assertIsInstance(node, Decorated)
        self.assertEqual(node.kind, "overline")

    def test_V_alias(self):
        node = parse_latex_string("\\V{F}")
        self.assertIsInstance(node, Decorated)
        self.assertEqual(node.kind, "overline")

    def test_underline(self):
        node = parse_latex_string("\\underline{text}")
        self.assertIsInstance(node, Decorated)
        self.assertEqual(node.kind, "underline")
        self.assertEqual(plain_text(node.body), "text")

    def test_underbar(self):
        node = parse_latex_string("\\underbar{text}")
        self.assertIsInstance(node, Decorated)
        self.assertEqual(node.kind, "underline")


# ─── Vectors (uvec, duvec, qvec) ─────────────────────────────────────────────


class TestVectors(unittest.TestCase):
    def test_uvec(self):
        node = parse_latex_string("\\uvec{V}{dir}")
        self.assertIsInstance(node, UnderOver)
        # base should be: underline(overline(V))
        base = node.base
        self.assertIsInstance(base, Decorated)
        self.assertEqual(base.kind, "underline")
        inner = base.body
        self.assertIsInstance(inner, Decorated)
        self.assertEqual(inner.kind, "overline")
        self.assertEqual(plain_text(inner.body), "V")
        self.assertIsNotNone(node.below)
        self.assertEqual(plain_text(node.below), "dir")

    def test_DirV_alias(self):
        node = parse_latex_string("\\DirV{V}{dir}")
        self.assertIsInstance(node, UnderOver)
        self.assertEqual(plain_text(node.below), "dir")

    def test_duvec(self):
        node = parse_latex_string("\\duvec{V}{dir}")
        self.assertIsInstance(node, UnderOver)
        base = node.base
        self.assertIsInstance(base, Decorated)
        self.assertEqual(base.kind, "underline")
        inner1 = base.body
        self.assertIsInstance(inner1, Decorated)
        self.assertEqual(inner1.kind, "underline")
        inner2 = inner1.body
        self.assertIsInstance(inner2, Decorated)
        self.assertEqual(inner2.kind, "overline")
        self.assertEqual(plain_text(node.below), "dir")

    def test_KnownV_alias(self):
        node = parse_latex_string("\\KnownV{V}{dir}")
        self.assertIsInstance(node, UnderOver)

    def test_qvec(self):
        node = parse_latex_string("\\qvec{V}")
        self.assertIsInstance(node, UnderOver)
        base = node.base
        self.assertIsInstance(base, Decorated)
        self.assertEqual(base.kind, "overline")
        self.assertEqual(plain_text(node.below), "??")

    def test_UnknownV_alias(self):
        node = parse_latex_string("\\UnknownV{V}")
        self.assertIsInstance(node, UnderOver)
        self.assertEqual(plain_text(node.below), "??")


# ─── Greek letters ───────────────────────────────────────────────────────────


class TestGreekLetters(unittest.TestCase):
    def test_alpha(self):
        node = parse_latex_string("\\alpha")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "α")

    def test_beta(self):
        node = parse_latex_string("\\beta")
        self.assertEqual(node.value, "β")

    def test_gamma(self):
        node = parse_latex_string("\\gamma")
        self.assertEqual(node.value, "γ")

    def test_delta(self):
        node = parse_latex_string("\\delta")
        self.assertEqual(node.value, "δ")

    def test_epsilon(self):
        node = parse_latex_string("\\epsilon")
        self.assertEqual(node.value, "ε")

    def test_varepsilon(self):
        node = parse_latex_string("\\varepsilon")
        self.assertEqual(node.value, "ε")

    def test_zeta(self):
        node = parse_latex_string("\\zeta")
        self.assertEqual(node.value, "ζ")

    def test_eta(self):
        node = parse_latex_string("\\eta")
        self.assertEqual(node.value, "η")

    def test_theta(self):
        node = parse_latex_string("\\theta")
        self.assertEqual(node.value, "θ")

    def test_vartheta(self):
        node = parse_latex_string("\\vartheta")
        self.assertEqual(node.value, "ϑ")

    def test_iota(self):
        node = parse_latex_string("\\iota")
        self.assertEqual(node.value, "ι")

    def test_kappa(self):
        node = parse_latex_string("\\kappa")
        self.assertEqual(node.value, "κ")

    def test_lambda(self):
        node = parse_latex_string("\\lambda")
        self.assertEqual(node.value, "λ")

    def test_mu(self):
        node = parse_latex_string("\\mu")
        self.assertEqual(node.value, "μ")

    def test_nu(self):
        node = parse_latex_string("\\nu")
        self.assertEqual(node.value, "ν")

    def test_xi(self):
        node = parse_latex_string("\\xi")
        self.assertEqual(node.value, "ξ")

    def test_pi(self):
        node = parse_latex_string("\\pi")
        self.assertEqual(node.value, "π")

    def test_varpi(self):
        node = parse_latex_string("\\varpi")
        self.assertEqual(node.value, "ϖ")

    def test_rho(self):
        node = parse_latex_string("\\rho")
        self.assertEqual(node.value, "ρ")

    def test_varrho(self):
        node = parse_latex_string("\\varrho")
        self.assertEqual(node.value, "ϱ")

    def test_sigma(self):
        node = parse_latex_string("\\sigma")
        self.assertEqual(node.value, "σ")

    def test_varsigma(self):
        node = parse_latex_string("\\varsigma")
        self.assertEqual(node.value, "ς")

    def test_tau(self):
        node = parse_latex_string("\\tau")
        self.assertEqual(node.value, "τ")

    def test_upsilon(self):
        node = parse_latex_string("\\upsilon")
        self.assertEqual(node.value, "υ")

    def test_phi(self):
        node = parse_latex_string("\\phi")
        self.assertEqual(node.value, "φ")

    def test_varphi(self):
        node = parse_latex_string("\\varphi")
        self.assertEqual(node.value, "ϕ")

    def test_chi(self):
        node = parse_latex_string("\\chi")
        self.assertEqual(node.value, "χ")

    def test_psi(self):
        node = parse_latex_string("\\psi")
        self.assertEqual(node.value, "ψ")

    def test_omega(self):
        node = parse_latex_string("\\omega")
        self.assertEqual(node.value, "ω")

    def test_uppercase_Gamma(self):
        node = parse_latex_string("\\Gamma")
        self.assertEqual(node.value, "Γ")

    def test_uppercase_Delta(self):
        node = parse_latex_string("\\Delta")
        self.assertEqual(node.value, "Δ")

    def test_uppercase_Theta(self):
        node = parse_latex_string("\\Theta")
        self.assertEqual(node.value, "Θ")

    def test_uppercase_Lambda(self):
        node = parse_latex_string("\\Lambda")
        self.assertEqual(node.value, "Λ")

    def test_uppercase_Xi(self):
        node = parse_latex_string("\\Xi")
        self.assertEqual(node.value, "Ξ")

    def test_uppercase_Pi(self):
        node = parse_latex_string("\\Pi")
        self.assertEqual(node.value, "Π")

    def test_uppercase_Sigma(self):
        node = parse_latex_string("\\Sigma")
        self.assertEqual(node.value, "Σ")

    def test_uppercase_Upsilon(self):
        node = parse_latex_string("\\Upsilon")
        self.assertEqual(node.value, "Υ")

    def test_uppercase_Phi(self):
        node = parse_latex_string("\\Phi")
        self.assertEqual(node.value, "Φ")

    def test_uppercase_Psi(self):
        node = parse_latex_string("\\Psi")
        self.assertEqual(node.value, "Ψ")

    def test_uppercase_Omega(self):
        node = parse_latex_string("\\Omega")
        self.assertEqual(node.value, "Ω")


# ─── Gost* aliases ───────────────────────────────────────────────────────────


class TestGostAliases(unittest.TestCase):
    def test_GostPhi(self):
        node = parse_latex_string("\\GostPhi")
        self.assertEqual(node.value, "Φ")

    def test_GostVarphi(self):
        node = parse_latex_string("\\GostVarphi")
        self.assertEqual(node.value, "φ")

    def test_GostMu(self):
        node = parse_latex_string("\\GostMu")
        self.assertEqual(node.value, "μ")

    def test_GostOmega(self):
        node = parse_latex_string("\\GostOmega")
        self.assertEqual(node.value, "ω")

    def test_GostEpsilon(self):
        node = parse_latex_string("\\GostEpsilon")
        self.assertEqual(node.value, "ε")

    def test_GostSum(self):
        node = parse_latex_string("\\GostSum")
        self.assertEqual(node.value, "∑")

    def test_GostAngle(self):
        node = parse_latex_string("\\GostAngle")
        self.assertEqual(node.value, "∠")

    def test_GostCdot(self):
        node = parse_latex_string("\\GostCdot")
        self.assertEqual(node.value, "·")

    def test_GostDeg(self):
        node = parse_latex_string("\\GostDeg")
        self.assertEqual(node.value, "°")

    def test_GostPrime(self):
        node = parse_latex_string("\\GostPrime")
        self.assertEqual(node.value, "′")

    def test_GostRightarrow(self):
        node = parse_latex_string("\\GostRightarrow")
        self.assertEqual(node.value, "=>")


# ─── Unknown command ─────────────────────────────────────────────────────────


class TestUnknownCommand(unittest.TestCase):
    def test_unknown_command_raises_valueerror(self):
        with self.assertRaises(ValueError) as ctx:
            parse_latex_string("\\unknowncommand")
        self.assertIn("Unknown command", str(ctx.exception))
        self.assertIn("position", str(ctx.exception))

    def test_unknown_command_in_group_raises(self):
        with self.assertRaises(ValueError) as ctx:
            parse_latex_string("{abc\\foo}")
        self.assertIn("Unknown command", str(ctx.exception))
        self.assertIn("position", str(ctx.exception))

    def test_position_reported(self):
        with self.assertRaises(ValueError) as ctx:
            parse_latex_string("x = \\badcommand + y")
        self.assertIn("position", str(ctx.exception))

    def test_unknown_command_in_script_raises(self):
        with self.assertRaises(ValueError) as ctx:
            parse_latex_string("a^{\\unknown}")
        self.assertIn("Unknown command", str(ctx.exception))


# ─── plain_text output ───────────────────────────────────────────────────────


class TestPlainText(unittest.TestCase):
    def test_plain_text_simple(self):
        node = parse_latex_string("Hello")
        self.assertEqual(plain_text(node), "Hello")

    def test_plain_text_fraction(self):
        node = parse_latex_string("\\frac{1}{2}")
        self.assertEqual(plain_text(node), "1/2")

    def test_plain_text_script_subscript(self):
        node = parse_latex_string("a_1")
        self.assertEqual(plain_text(node), "a_(1)")

    def test_plain_text_script_both(self):
        node = parse_latex_string("a_1^2")
        self.assertEqual(plain_text(node), "a^(2)_(1)")

    def test_plain_text_overline(self):
        node = parse_latex_string("\\overline{ABC}")
        self.assertEqual(plain_text(node), "ABC")

    def test_plain_text_sequence(self):
        node = parse_latex_string("ab{cd}ef")
        self.assertEqual(plain_text(node), "abcdef")

    def test_plain_text_mixed(self):
        node = parse_latex_string("a\\alpha{}b")
        self.assertEqual(plain_text(node), "aαb")

    def test_plain_text_script_upper_only(self):
        node = parse_latex_string("a^{2}")
        self.assertEqual(plain_text(node), "a^(2)")

    def test_plain_text_prime(self):
        """f' should remain as f' in plain text (text char, not prime modifier)."""
        node = parse_latex_string("f'")
        self.assertEqual(plain_text(node), "f'")


# ─── parse_latex_document ────────────────────────────────────────────────────


class TestParseLatexDocument(unittest.TestCase):
    def test_single_line(self):
        nodes = parse_latex_document("hello")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(plain_text(nodes[0]), "hello")

    def test_multi_line_with_double_backslash(self):
        nodes = parse_latex_document("line1\\\\line2")
        self.assertEqual(len(nodes), 2)
        self.assertEqual(plain_text(nodes[0]), "line1")
        self.assertEqual(plain_text(nodes[1]), "line2")

    def test_dollars_removed(self):
        nodes = parse_latex_document("$x^2$")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(plain_text(nodes[0]), "x^(2)")

    def test_double_dollars_removed(self):
        nodes = parse_latex_document("$$x$$")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(plain_text(nodes[0]), "x")

    def test_math_mode_brackets_removed(self):
        nodes = parse_latex_document("\\[x\\]")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(plain_text(nodes[0]), "x")

    def test_empty_input_returns_text_empty(self):
        nodes = parse_latex_document("")
        self.assertEqual(len(nodes), 1)
        self.assertIsInstance(nodes[0], Text)
        self.assertEqual(nodes[0].value, "")

    def test_whitespace_only_returns_text_empty(self):
        nodes = parse_latex_document("   ")
        self.assertEqual(len(nodes), 1)
        self.assertIsInstance(nodes[0], Text)
        self.assertEqual(nodes[0].value, "")

    def test_double_backslash_with_spaces(self):
        nodes = parse_latex_document("  a  \\\\  b  ")
        self.assertEqual(len(nodes), 2)
        self.assertEqual(plain_text(nodes[0]), "a")
        self.assertEqual(plain_text(nodes[1]), "b")


# ─── Compact and merge ───────────────────────────────────────────────────────


class TestCompactAndMerge(unittest.TestCase):
    def test_adjacent_text_merged(self):
        node = parse_latex_string("ab")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "ab")

    def test_text_separated_by_group_merged(self):
        node = parse_latex_string("a{b}c")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "abc")

    def test_command_and_text_merged(self):
        node = parse_latex_string("a\\alpha{}b")
        # \alpha is Text("α"), so "a" + "α" + "" + "b" = "aαb"
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "aαb")

    def test_mixed_text_and_nontext(self):
        node = parse_latex_string("a\\frac{1}{2}b")
        self.assertIsInstance(node, Sequence)
        self.assertEqual(len(node.parts), 3)
        self.assertIsInstance(node.parts[0], Text)
        self.assertIsInstance(node.parts[1], Fraction)
        self.assertIsInstance(node.parts[2], Text)
        self.assertEqual(plain_text(node), "a1/2b")

    def test_floating_script_attached(self):
        """^{x} attached to previous text when it appears without a base."""
        node = parse_latex_string("a^{x}")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.base), "a")
        self.assertEqual(plain_text(node.superscript), "x")

    def test_supsp_creates_floating_script(self):
        node = parse_latex_string("\\supsp{x}")
        self.assertIsInstance(node, Script)
        self.assertIsInstance(node.base, Text)
        self.assertEqual(node.base.value, "")

    def test_floating_script_attaches_to_previous(self):
        node = parse_latex_string("ab\\supsp{x}")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.base), "ab")
        self.assertEqual(plain_text(node.superscript), "x")


# ─── Special commands ────────────────────────────────────────────────────────


class TestSpecialCommands(unittest.TestCase):
    def test_supsp(self):
        node = parse_latex_string("\\supsp{x}")
        self.assertIsInstance(node, Script)
        self.assertIsInstance(node.base, Text)
        self.assertEqual(node.base.value, "")
        self.assertEqual(plain_text(node.superscript), "x")

    def test_Sup_alias(self):
        node = parse_latex_string("\\Sup{x}")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.superscript), "x")

    def test_underset(self):
        node = parse_latex_string("\\underset{below}{base}")
        self.assertIsInstance(node, UnderOver)
        self.assertEqual(plain_text(node.base), "base")
        self.assertEqual(plain_text(node.below), "below")

    def test_overset(self):
        node = parse_latex_string("\\overset{above}{base}")
        self.assertIsInstance(node, UnderOver)
        self.assertEqual(plain_text(node.base), "base")
        self.assertEqual(plain_text(node.above), "above")

    def test_left_right_noop(self):
        node = parse_latex_string("\\left( x \\right)")
        # \left and \right produce empty Text nodes that merge with neighbours
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "( x )")

    def test_text_command(self):
        node = parse_latex_string("\\text{abc}")
        self.assertEqual(plain_text(node), "abc")

    def test_mathrm_command_is_transparent(self):
        node = parse_latex_string("\\mathrm{abc}")
        self.assertEqual(plain_text(node), "abc")

    def test_operatorname_command(self):
        node = parse_latex_string("\\operatorname{sym}")
        self.assertEqual(plain_text(node), "sym")

    def test_left_right_balanced(self):
        node = parse_latex_string("\\left( x + y \\right)")
        self.assertEqual(plain_text(node), "( x + y )")


# ─── Spacing and non‑alpha commands ──────────────────────────────────────────


class TestSpacingCommands(unittest.TestCase):
    def test_quad(self):
        node = parse_latex_string("a\\quad b")
        # \quad contributes one space + literal space before b = 2 spaces
        self.assertEqual(plain_text(node), "a  b")

    def test_qquad(self):
        node = parse_latex_string("a\\qquad b")
        # \qquad contributes two spaces + literal space before b = 3 spaces
        self.assertEqual(plain_text(node), "a   b")

    def test_backslash_space(self):
        node = parse_latex_string("a\\ b")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "a b")

    def test_backslash_comma(self):
        node = parse_latex_string("a\\,b")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "ab")

    def test_backslash_semicolon(self):
        node = parse_latex_string("a\\;b")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "a b")

    def test_backslash_colon(self):
        node = parse_latex_string("a\\:b")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "a b")

    def test_backslash_exclamation(self):
        node = parse_latex_string("a\\!b")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "ab")


# ─── Other command mappings ──────────────────────────────────────────────────


class TestOtherCommands(unittest.TestCase):
    def test_prime(self):
        node = parse_latex_string("\\prime")
        self.assertEqual(node.value, "′")

    def test_circ(self):
        node = parse_latex_string("\\circ")
        self.assertEqual(node.value, "°")

    def test_ldots(self):
        node = parse_latex_string("\\ldots")
        self.assertEqual(node.value, "…")

    def test_cdots(self):
        node = parse_latex_string("\\cdots")
        self.assertEqual(node.value, "⋯")

    def test_cdot(self):
        node = parse_latex_string("\\cdot")
        self.assertEqual(node.value, "·")

    def test_times(self):
        node = parse_latex_string("\\times")
        self.assertEqual(node.value, "×")

    def test_pm(self):
        node = parse_latex_string("\\pm")
        self.assertEqual(node.value, "±")

    def test_mp(self):
        node = parse_latex_string("\\mp")
        self.assertEqual(node.value, "∓")

    def test_leq(self):
        node = parse_latex_string("\\leq")
        self.assertEqual(node.value, "≤")

    def test_geq(self):
        node = parse_latex_string("\\geq")
        self.assertEqual(node.value, "≥")

    def test_neq(self):
        node = parse_latex_string("\\neq")
        self.assertEqual(node.value, "≠")

    def test_approx(self):
        node = parse_latex_string("\\approx")
        self.assertEqual(node.value, "≈")

    def test_to(self):
        node = parse_latex_string("\\to")
        self.assertEqual(node.value, "->")

    def test_rightarrow(self):
        node = parse_latex_string("\\rightarrow")
        self.assertEqual(node.value, "->")

    def test_leftarrow(self):
        node = parse_latex_string("\\leftarrow")
        self.assertEqual(node.value, "←")

    def test_leftrightarrow(self):
        node = parse_latex_string("\\leftrightarrow")
        self.assertEqual(node.value, "↔")

    def test_degree(self):
        node = parse_latex_string("\\degree")
        self.assertEqual(node.value, "°")

    def test_parallel(self):
        node = parse_latex_string("\\parallel")
        self.assertEqual(node.value, "||")

    def test_Sum(self):
        node = parse_latex_string("\\sum")
        self.assertEqual(node.value, "∑")

    def test_integral(self):
        node = parse_latex_string("\\int")
        self.assertEqual(node.value, "∫")

    def test_angle(self):
        node = parse_latex_string("\\angle")
        self.assertEqual(node.value, "∠")

    def test_Rightarrow(self):
        node = parse_latex_string("\\Rightarrow")
        self.assertEqual(node.value, "=>")


# ─── LatexParser position checks ─────────────────────────────────────────────


class TestLatexParserPosition(unittest.TestCase):
    def test_parse_consumes_all(self):
        parser = LatexParser("hello")
        self.assertEqual(parser.pos, 0)
        parser.parse()
        self.assertEqual(parser.pos, 5)

    def test_trailing_input_ignored(self):
        """Whitespace after content is consumed by skip_space, not trailing."""
        node = parse_latex_string("abc def")
        self.assertEqual(plain_text(node), "abc def")

    def test_parse_forwards_only(self):
        """Verify the parser moves forward and consumes all input."""
        parser = LatexParser("a b")
        node = parser.parse()
        self.assertEqual(parser.pos, 3)
        self.assertEqual(plain_text(node), "a b")


# ─── count_primes ────────────────────────────────────────────────────────────


class TestCountPrimes(unittest.TestCase):
    def test_none_returns_zero(self):
        self.assertEqual(count_primes(None), 0)

    def test_single_prime(self):
        node = parse_latex_string("'")
        self.assertEqual(count_primes(node), 1)

    def test_double_prime(self):
        node = parse_latex_string("''")
        self.assertEqual(count_primes(node), 2)

    def test_non_prime_returns_zero(self):
        node = parse_latex_string("abc")
        self.assertEqual(count_primes(node), 0)

    def test_mixed_chars_returns_zero(self):
        node = parse_latex_string("a'")
        self.assertEqual(count_primes(node), 0)


# ─── plain_node_text ─────────────────────────────────────────────────────────


class TestPlainNodeText(unittest.TestCase):
    def test_text_node(self):
        node = Text("hello")
        self.assertEqual(plain_node_text(node), "hello")

    def test_sequence(self):
        node = Sequence([Text("a"), Text("b")])
        self.assertEqual(plain_node_text(node), "ab")

    def test_decorated(self):
        node = Decorated(kind="overline", body=Text("X"))
        self.assertEqual(plain_node_text(node), "X")

    def test_other_returns_empty(self):
        node = Fraction(numerator=Text("1"), denominator=Text("2"))
        self.assertEqual(plain_node_text(node), "")


# ─── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def test_empty_string(self):
        node = parse_latex_string("")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "")

    def test_only_backslash(self):
        node = parse_latex_string("\\")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "\\")

    def test_backslash_bracket_left(self):
        node = parse_latex_string("\\[")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "")

    def test_backslash_bracket_right(self):
        node = parse_latex_string("\\]")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "")

    def test_backslash_tick(self):
        node = parse_latex_string("\\`")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "`")

    def test_perp_symbol(self):
        node = parse_latex_string("\\perp")
        self.assertEqual(plain_text(node), "⊥")

    def test_GostPerp(self):
        node = parse_latex_string("\\GostPerp")
        self.assertEqual(plain_text(node), "⊥")

    def test_unicode_in_text(self):
        node = parse_latex_string("αβγ")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "αβγ")

    def test_backslash_non_alpha_returns_raw(self):
        node = parse_latex_string("\\#")
        self.assertIsInstance(node, Text)
        self.assertEqual(node.value, "#")

    def test_script_with_unicode_greek(self):
        node = parse_latex_string("F_{32}^{τ}")
        self.assertIsInstance(node, Script)
        self.assertEqual(plain_text(node.base), "F")
        self.assertEqual(plain_text(node.subscript), "32")
        self.assertEqual(plain_text(node.superscript), "τ")


# ─── Parse errors ────────────────────────────────────────────────────────────


class TestParseErrors(unittest.TestCase):
    def test_unknown_command_position_is_correct(self):
        source = "x \\foo y"
        try:
            parse_latex_string(source)
            self.fail("Expected ValueError")
        except ValueError as exc:
            msg = str(exc)
            # The backslash is at position 2
            self.assertIn("position 2", msg)

    def test_unclosed_group_position_is_correct(self):
        source = "a{b"
        try:
            parse_latex_string(source)
            self.fail("Expected ValueError")
        except ValueError as exc:
            msg = str(exc)
            # The { is at position 1
            self.assertIn("position 1", msg)

    def test_nested_unclosed_group_position(self):
        source = "{a{b}"
        try:
            parse_latex_string(source)
            self.fail("Expected ValueError")
        except ValueError as exc:
            msg = str(exc)
            # The outer { is at position 0 (the inner {b} is properly closed)
            self.assertIn("position 0", msg)

    def test_frac_expected_brace(self):
        source = "\\frac 1{2}"
        try:
            parse_latex_string(source)
            self.fail("Expected ValueError")
        except ValueError as exc:
            msg = str(exc)
            self.assertIn("position", msg)


# ─── M3: FontRole ───────────────────────────────────────────────────────────


class TestFontRole(unittest.TestCase):
    """FontRole enum has expected members."""

    def test_gost_type_a_exists(self):
        from tmm_scene_kompas.kompas_text import FontRole
        self.assertTrue(hasattr(FontRole, 'GOST_TYPE_A'))

    def test_symbol_exists(self):
        from tmm_scene_kompas.kompas_text import FontRole
        self.assertTrue(hasattr(FontRole, 'SYMBOL'))

    def test_distinct_members(self):
        from tmm_scene_kompas.kompas_text import FontRole
        self.assertIsNot(FontRole.GOST_TYPE_A, FontRole.SYMBOL)
        self.assertEqual(FontRole.GOST_TYPE_A.name, 'GOST_TYPE_A')
        self.assertEqual(FontRole.SYMBOL.name, 'SYMBOL')


# ─── M3: TextPlan types ─────────────────────────────────────────────────────


class TestTextPlanTypes(unittest.TestCase):
    """TextItemPlan, TextLinePlan, TextRenderPlan construction."""

    def test_text_item_plan_creation(self):
        from tmm_scene_kompas.kompas_text import FontRole, TextItemPlan
        item = TextItemPlan(item_type=0, kind="plain",
                            font=FontRole.GOST_TYPE_A, content="Hello")
        self.assertEqual(item.item_type, 0)
        self.assertEqual(item.kind, "plain")
        self.assertIs(item.font, FontRole.GOST_TYPE_A)
        self.assertEqual(item.content, "Hello")

    def test_text_line_plan_creation(self):
        from tmm_scene_kompas.kompas_text import (
            FontRole, TextItemPlan, TextLinePlan
        )
        items = [
            TextItemPlan(item_type=0, kind="script_base",
                         font=FontRole.GOST_TYPE_A, content="F"),
            TextItemPlan(item_type=0, kind="script_lower",
                         font=FontRole.GOST_TYPE_A, content="32"),
            TextItemPlan(item_type=0, kind="script_end",
                         font=FontRole.GOST_TYPE_A, content=""),
        ]
        line = TextLinePlan(items=items)
        self.assertEqual(len(line.items), 3)

    def test_text_render_plan_creation(self):
        from tmm_scene_kompas.kompas_text import (
            FontRole, TextItemPlan, TextLinePlan, TextRenderPlan
        )
        items = [TextItemPlan(item_type=0, kind="plain",
                              font=FontRole.GOST_TYPE_A, content="x")]
        line = TextLinePlan(items=items)
        plan = TextRenderPlan(lines=[line], height=3.5)
        self.assertEqual(len(plan.lines), 1)
        self.assertAlmostEqual(plan.height, 3.5)

    def test_default_height(self):
        from tmm_scene_kompas.kompas_text import (
            TextLinePlan, TextRenderPlan
        )
        plan = TextRenderPlan(lines=[TextLinePlan(items=[])])
        self.assertAlmostEqual(plan.height, 5.0)


# ─── M3: Greek → Symbol slot mapping ────────────────────────────────────────


class TestGreekToSymbolSlots(unittest.TestCase):
    """Verify Greek Unicode → Symbol font ASCII slot mapping.

    The Symbol font maps Greek letters to Latin ASCII positions
    (prototype slots) — Φ→F, φ→f, ω→w, ε→e, τ→t, μ→m, etc.
    """

    def test_capital_phi_maps_to_F(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03A6')  # Φ
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 'F')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_small_phi_maps_to_f(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03C6')  # φ
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 'f')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_variant_phi_maps_to_same_f_slot_as_paperclip(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03D5')  # ϕ
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 'f')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_omega_maps_to_w(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03C9')  # ω
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 'w')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_epsilon_maps_to_e(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03B5')  # ε
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 'e')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_tau_maps_to_t(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03C4')  # τ
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 't')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_mu_maps_to_m(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03BC')  # μ
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 'm')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_alpha_maps_to_a(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03B1')  # α
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 'a')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_beta_maps_to_b(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03B2')  # β
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 'b')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_capital_omega_maps_to_W(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('\u03A9')  # Ω
        item = plan.lines[0].items[0]
        self.assertEqual(item.content, 'W')
        self.assertEqual(item.font.name, 'SYMBOL')

    def test_mixed_latin_and_greek(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        # First Latin, then Greek — should produce separate items
        plan = compile_unicode_text('a\u03B2g')  # aβg
        items = plan.lines[0].items
        self.assertEqual(len(items), 3)
        # First: "a" in GOST
        self.assertEqual(items[0].content, 'a')
        self.assertEqual(items[0].font.name, 'GOST_TYPE_A')
        # Second: "b" in SYMBOL (β → b)
        self.assertEqual(items[1].content, 'b')
        self.assertEqual(items[1].font.name, 'SYMBOL')
        # Third: "g" in GOST
        self.assertEqual(items[2].content, 'g')
        self.assertEqual(items[2].font.name, 'GOST_TYPE_A')


# ─── M3: compile_unicode_text ───────────────────────────────────────────────


class TestCompileUnicodeText(unittest.TestCase):
    """compile_unicode_text — plain text with Unicode detection."""

    def test_plain_text(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text("Hello")
        items = plan.lines[0].items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, 0)
        self.assertEqual(items[0].kind, 'plain')
        self.assertEqual(items[0].content, 'Hello')
        self.assertEqual(items[0].font.name, 'GOST_TYPE_A')

    def test_empty_text(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text("")
        items = plan.lines[0].items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, 0)
        self.assertEqual(items[0].kind, 'plain')
        self.assertEqual(items[0].content, '')

    def test_unicode_dashes_map_to_ascii_hyphen(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text("left – middle — right")
        self.assertEqual(plan.lines[0].items[0].content,
                         "left - middle - right")

    def test_F_subscript_32_base_lower_end(self):
        """F₃₂ → script_base, script_lower, script_end."""
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        text = 'F\u2083\u2082'
        plan = compile_unicode_text(text)
        items = plan.lines[0].items
        self.assertGreaterEqual(len(items), 3)
        self.assertEqual(items[0].kind, 'script_base')
        self.assertEqual(items[0].content, 'F')
        self.assertEqual(items[0].font.name, 'GOST_TYPE_A')
        self.assertEqual(items[1].kind, 'script_lower')
        self.assertEqual(items[1].content, '32')
        self.assertEqual(items[1].font.name, 'GOST_TYPE_A')
        self.assertEqual(items[2].kind, 'script_end')
        self.assertEqual(items[2].content, '')

    def test_superscript_2(self):
        """x² → script_base, script_upper, script_end."""
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('x\u00B2')  # x²
        items = plan.lines[0].items
        self.assertGreaterEqual(len(items), 3)
        self.assertEqual(items[0].kind, 'script_base')
        self.assertEqual(items[0].content, 'x')
        self.assertEqual(items[1].kind, 'script_upper')
        self.assertEqual(items[1].content, '2')
        self.assertEqual(items[2].kind, 'script_end')

    def test_superscript_3(self):
        """x³ → script_upper."""
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('x\u00B3')
        items = plan.lines[0].items
        self.assertEqual(items[1].kind, 'script_upper')
        self.assertEqual(items[1].content, '3')

    def test_degree_compile_to_amp01(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('100\u00B0C')
        items = plan.lines[0].items
        self.assertGreaterEqual(len(items), 3)
        degree_items = [i for i in items if '&01' in i.content]
        self.assertEqual(len(degree_items), 1)
        self.assertEqual(degree_items[0].content, '&01')

    def test_superscript_and_subscript_together(self):
        """x²₃ → script_base, script_upper, script_lower, script_end."""
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('x\u00B2\u2083')  # x²₃
        items = plan.lines[0].items
        self.assertGreaterEqual(len(items), 4)
        self.assertEqual(items[0].kind, 'script_base')
        self.assertEqual(items[0].content, 'x')
        self.assertEqual(items[1].kind, 'script_upper')
        self.assertEqual(items[1].content, '2')
        self.assertEqual(items[2].kind, 'script_lower')
        self.assertEqual(items[2].content, '3')
        self.assertEqual(items[3].kind, 'script_end')

    def test_mixed_greek_latin_unicode(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text('A\u03B1B')  # AαB
        items = plan.lines[0].items
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].content, 'A')
        self.assertEqual(items[0].font.name, 'GOST_TYPE_A')
        self.assertEqual(items[1].content, 'a')
        self.assertEqual(items[1].font.name, 'SYMBOL')
        self.assertEqual(items[2].content, 'B')
        self.assertEqual(items[2].font.name, 'GOST_TYPE_A')


# ─── M3: compile_latex ──────────────────────────────────────────────────────


class TestCompileLatex(unittest.TestCase):
    """compile_latex — AST to KOMPAS text items."""

    def test_plain_text(self):
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex("Hello")
        items = plan.lines[0].items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, 0)
        self.assertEqual(items[0].kind, 'plain')
        self.assertEqual(items[0].content, "Hello")
        self.assertEqual(items[0].font.name, "GOST_TYPE_A")

    def test_simple_subscript(self):
        """F_{32} → script_base, script_lower, script_end."""
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex(r"F_{32}")
        items = plan.lines[0].items
        self.assertGreaterEqual(len(items), 3)
        self.assertEqual(items[0].kind, 'script_base')
        self.assertEqual(items[0].content, "F")
        self.assertEqual(items[1].kind, 'script_lower')
        self.assertEqual(items[1].content, "32")
        self.assertEqual(items[2].kind, 'script_end')

    def test_simple_superscript(self):
        """F^{2} → script_base, script_upper, script_end."""
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex(r"F^{2}")
        items = plan.lines[0].items
        self.assertGreaterEqual(len(items), 3)
        self.assertEqual(items[0].kind, 'script_base')
        self.assertEqual(items[0].content, "F")
        self.assertEqual(items[1].kind, 'script_upper')
        self.assertEqual(items[1].content, "2")
        self.assertEqual(items[2].kind, 'script_end')

    def test_F_32_tau_script_items(self):
        """F_{32}^{\tau} → kinds [script_base, script_upper, script_lower, script_end].

        Upper τ maps to Symbol 't'; lower 32 is GOST.
        """
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex(r"F_{32}^{\tau}")
        items = plan.lines[0].items
        kinds = [i.kind for i in items]
        self.assertEqual(kinds, ['script_base', 'script_upper',
                                  'script_lower', 'script_end'])

        # Upper τ → content='t', font=SYMBOL
        upper = items[1]
        self.assertEqual(upper.kind, 'script_upper')
        self.assertEqual(upper.content, 't')
        self.assertEqual(upper.font.name, 'SYMBOL')

        # Lower 32 → content='32', font=GOST_TYPE_A
        lower = items[2]
        self.assertEqual(lower.kind, 'script_lower')
        self.assertEqual(lower.content, '32')
        self.assertEqual(lower.font.name, 'GOST_TYPE_A')

        # Terminator
        self.assertEqual(items[3].kind, 'script_end')
        self.assertEqual(items[3].content, '')

    def test_fraction_types(self):
        """\frac{a}{b} → types [1, 2, 3]."""
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex(r"\frac{a}{b}")
        items = plan.lines[0].items
        types = [i.item_type for i in items]
        self.assertEqual(types, [1, 2, 3])
        self.assertEqual(items[0].content, 'a')
        self.assertEqual(items[1].content, 'b')
        self.assertEqual(items[2].content, '')

    def test_fraction_numbers(self):
        """\frac{1}{2} → [1, 2, 3] with content '1', '2', ''."""
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex(r"\frac{1}{2}")
        items = plan.lines[0].items
        types = [i.item_type for i in items]
        self.assertEqual(types, [1, 2, 3])
        self.assertEqual(items[0].content, '1')
        self.assertEqual(items[1].content, '2')

    def test_decorated_uses_editable_special_symbol_items(self):
        """Decorations are one editable special-symbol text sequence."""
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex(r"\overline{ABC}")
        items = plan.lines[0].items
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].kind, 'special')
        self.assertEqual(items[0].content, 'ABC')
        self.assertEqual(items[0].i_s_numb, 95)
        self.assertEqual(items[1].kind, 'special_end')

    def test_sequence(self):
        """a+\frac{1}{2}b → multiple items."""
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex(r"a+\frac{1}{2}b")
        items = plan.lines[0].items
        self.assertGreaterEqual(len(items), 5)
        self.assertEqual(items[0].kind, 'plain')
        self.assertEqual(items[0].content, 'a+')
        # fraction
        self.assertEqual(items[1].item_type, 1)
        self.assertEqual(items[2].item_type, 2)
        self.assertEqual(items[3].item_type, 3)
        # trailing
        self.assertEqual(items[4].kind, 'plain')
        self.assertEqual(items[4].content, 'b')

    def test_accepts_ast_node(self):
        from tmm_scene_kompas.kompas_text import (
            Text, compile_latex
        )
        plan = compile_latex(Text("AST"))
        items = plan.lines[0].items
        self.assertEqual(items[0].content, 'AST')


# ─── M3: estimate_plan_size ─────────────────────────────────────────────────


class TestEstimatePlanSize(unittest.TestCase):
    """estimate_plan_size — approximate size of a render plan."""

    def test_single_line(self):
        from tmm_scene_kompas.kompas_text import (
            FontRole, TextItemPlan, TextLinePlan, TextRenderPlan,
            estimate_plan_size,
        )
        items = [
            TextItemPlan(item_type=0, kind="plain",
                         font=FontRole.GOST_TYPE_A, content="Hello")
        ]
        plan = TextRenderPlan(lines=[TextLinePlan(items=items)], height=5.0)
        w, h = estimate_plan_size(plan)
        # 5 chars * 5.0 * 0.7 = 17.5
        self.assertAlmostEqual(w, 17.5)
        # 1 line * 5.0 * 1.4 = 7.0
        self.assertAlmostEqual(h, 7.0)

    def test_empty_plan(self):
        from tmm_scene_kompas.kompas_text import (
            FontRole, TextItemPlan, TextLinePlan, TextRenderPlan,
            estimate_plan_size,
        )
        plan = TextRenderPlan(
            lines=[
                TextLinePlan(
                    items=[
                        TextItemPlan(
                            item_type=0, kind="plain",
                            font=FontRole.GOST_TYPE_A, content=""
                        )
                    ]
                )
            ],
            height=5.0,
        )
        w, h = estimate_plan_size(plan)
        self.assertAlmostEqual(w, 3.5)  # min 1 char
        self.assertAlmostEqual(h, 7.0)

    def test_control_syntax_size_uses_visible_glyphs(self):
        from tmm_scene_kompas.kompas_text import (
            FontRole, TextItemPlan, TextLinePlan, TextRenderPlan,
            estimate_plan_size,
        )
        item = TextItemPlan(
            item_type=0, kind="plain", font=FontRole.GOST_TYPE_A,
            content="@+95~$(^(Symbol type A)+70~)$$;5$",
        )
        plan = TextRenderPlan(
            lines=[TextLinePlan(items=[item])], height=5.0
        )
        w, h = estimate_plan_size(plan)
        self.assertAlmostEqual(w, 7.0)  # Phi + subscript 5
        self.assertAlmostEqual(h, 7.0)

    def test_custom_height(self):
        from tmm_scene_kompas.kompas_text import (
            FontRole, TextItemPlan, TextLinePlan, TextRenderPlan,
            estimate_plan_size,
        )
        items = [
            TextItemPlan(item_type=0, kind="plain",
                         font=FontRole.GOST_TYPE_A, content="AB")
        ]
        plan = TextRenderPlan(lines=[TextLinePlan(items=items)], height=3.0)
        w, h = estimate_plan_size(plan)
        # 2 * 3.0 * 0.7 = 4.2
        self.assertAlmostEqual(w, 4.2)
        # 1 * 3.0 * 1.4 = 4.2
        self.assertAlmostEqual(h, 4.2)


# ─── Exact one-object API5 compilation ─────────────────────────────────────


class TestCompileLatexApi5Exact(unittest.TestCase):
    def test_nested_phi_uses_paperclip_symbol_slot(self):
        from tmm_scene_kompas.kompas_text import compile_latex_api5_exact
        plan = compile_latex_api5_exact(r"\Phi_{5}")
        self.assertEqual(plan.lines[0].items[0].content, "^(Symbol type A)+70~$;5$")

    def test_script_uses_control_syntax(self):
        from tmm_scene_kompas.kompas_text import compile_latex_api5_exact
        plan = compile_latex_api5_exact(r"F_{32}^{t}")
        self.assertEqual(len(plan.lines[0].items), 1)
        self.assertEqual(plan.lines[0].items[0].content, "F$t;32$")

    def test_under_over_uses_s_flags(self):
        from tmm_scene_kompas.kompas_text import compile_latex_api5_exact
        plan = compile_latex_api5_exact(r"\overset{UP}{F}")
        self.assertEqual([i.kind for i in plan.lines[0].items],
                         ["updn_base", "updn_upper", "updn_end"])

    def test_under_over_annotation_is_one_height_step_smaller(self):
        from tmm_scene_kompas.kompas_text import compile_latex_api5_exact
        plan = compile_latex_api5_exact(r"\underset{below}{F}", height=5.0)
        items = plan.lines[0].items
        self.assertIsNone(items[0].height)
        self.assertEqual(items[1].height, 3.5)
        self.assertEqual(items[2].height, None)

    def test_nested_index_inside_under_over(self):
        from tmm_scene_kompas.kompas_text import compile_latex_api5_exact
        plan = compile_latex_api5_exact(r"\overset{U^2_3}{F_{32}^{t}}")
        self.assertEqual(plan.lines[0].items[0].content, "F$t;32$")
        self.assertEqual(plan.lines[0].items[1].content, "U$2;3$")

    def test_underset_inside_sequence_remains_structural(self):
        from tmm_scene_kompas.kompas_text import compile_latex_api5_exact
        plan = compile_latex_api5_exact(
            r"?\qquad\underset{\perp AB}{\underline{\overline{a}_{BA}^{\tau}}}TAIL"
        )
        kinds = [item.kind for item in plan.lines[0].items]
        self.assertIn("updn_base", kinds)
        self.assertIn("updn_lower", kinds)
        end = kinds.index("updn_end")
        self.assertTrue(any(item.content.endswith("TAIL")
                            for item in plan.lines[0].items[end + 1:]))

    def test_fraction_inside_sequence_is_not_nested_control_syntax(self):
        from tmm_scene_kompas.kompas_text import compile_latex_api5_exact
        plan = compile_latex_api5_exact(
            r"F_{21}^{\tau}=\frac{1}{l_{BC}}(M_{\Phi2}+\Phi_2)TAIL"
        )
        items = plan.lines[0].items
        kinds = [item.kind for item in items]
        self.assertEqual(kinds.count("fraction_num"), 1)
        self.assertEqual(kinds.count("fraction_den"), 1)
        self.assertEqual(kinds.count("fraction_end"), 1)
        self.assertFalse(any("$d" in item.content for item in items))
        fraction_end = kinds.index("fraction_end")
        self.assertTrue(any("TAIL" in item.content for item in items[fraction_end + 1:]))

    def test_script_state_is_closed_before_following_text(self):
        from tmm_scene_kompas.kompas_text import compile_latex_api5_exact
        plan = compile_latex_api5_exact(r"M_{\Phi2}+AFTER")
        items = plan.lines[0].items
        self.assertGreaterEqual(len(items), 2)
        self.assertIn("M$;", items[0].content)
        self.assertEqual(items[-1].kind, "plain")
        self.assertEqual(items[-1].content, "+AFTER")


# ─── M3: Prohibited types ───────────────────────────────────────────────────


class TestNoProhibitedTypes(unittest.TestCase):
    """Ensure no types 17, 18, 20, 24 appear in compiled output."""

    def _get_types(self, plan):
        result = []
        for line in plan.lines:
            for item in line.items:
                result.append(item.item_type)
        return result

    def test_plain_text_no_prohibited(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        plan = compile_unicode_text("Test")
        types = self._get_types(plan)
        for t in types:
            self.assertNotIn(t, (17, 18, 20, 24))

    def test_script_no_prohibited(self):
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex(r"F_{32}^{\tau}")
        types = self._get_types(plan)
        for t in types:
            self.assertNotIn(t, (17, 18, 20, 24))

    def test_fraction_no_prohibited(self):
        from tmm_scene_kompas.kompas_text import compile_latex
        plan = compile_latex(r"\frac{1}{2}")
        types = self._get_types(plan)
        self.assertEqual(types, [1, 2, 3])
        for t in types:
            self.assertNotIn(t, (17, 18, 20, 24))


# ─── M3: Unsupported codepoint error ────────────────────────────────────────


class TestUnsupportedCodepoint(unittest.TestCase):
    """Unsupported codepoint raises ValueError."""

    def test_control_char_raises(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        with self.assertRaises(ValueError) as ctx:
            compile_unicode_text("a\x00b")
        self.assertIn("Unsupported", str(ctx.exception))

    def test_delete_char_raises(self):
        from tmm_scene_kompas.kompas_text import compile_unicode_text
        with self.assertRaises(ValueError) as ctx:
            compile_unicode_text("a\x7fb")
        self.assertIn("Unsupported", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

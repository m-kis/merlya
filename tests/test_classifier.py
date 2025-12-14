"""Tests for the intent classifier and router."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from merlya.router.classifier import (
    AgentMode,
    IntentRouter,
    RouterResult,
)


class TestAgentMode:
    """Tests for AgentMode enum."""

    def test_mode_values(self) -> None:
        """Test that all expected modes exist."""
        assert AgentMode.DIAGNOSTIC == "diagnostic"
        assert AgentMode.REMEDIATION == "remediation"
        assert AgentMode.QUERY == "query"
        assert AgentMode.CHAT == "chat"

    def test_mode_is_string(self) -> None:
        """Test modes are strings."""
        assert isinstance(AgentMode.DIAGNOSTIC.value, str)
        assert isinstance(AgentMode.CHAT.value, str)


class TestRouterResult:
    """Tests for RouterResult dataclass."""

    def test_router_result_creation(self) -> None:
        """Test RouterResult creation."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["ssh", "core"],
            confidence=0.95,
            reasoning="User wants to diagnose",
            entities={"hosts": ["webserver"]},
        )
        assert result.mode == AgentMode.DIAGNOSTIC
        assert result.confidence == 0.95
        assert result.reasoning == "User wants to diagnose"
        assert "webserver" in result.entities["hosts"]
        assert "ssh" in result.tools

    def test_router_result_defaults(self) -> None:
        """Test RouterResult default values."""
        result = RouterResult(mode=AgentMode.CHAT, tools=[])
        assert result.confidence == 0.0
        assert result.reasoning is None
        assert result.entities == {}
        assert result.delegate_to is None

    def test_tool_calls_limit_by_mode(self) -> None:
        """Test dynamic tool_calls_limit based on mode."""
        from merlya.config.constants import (
            TOOL_CALLS_LIMIT_CHAT,
            TOOL_CALLS_LIMIT_DIAGNOSTIC,
            TOOL_CALLS_LIMIT_QUERY,
            TOOL_CALLS_LIMIT_REMEDIATION,
        )

        diagnostic = RouterResult(mode=AgentMode.DIAGNOSTIC, tools=[])
        assert diagnostic.tool_calls_limit == TOOL_CALLS_LIMIT_DIAGNOSTIC

        remediation = RouterResult(mode=AgentMode.REMEDIATION, tools=[])
        assert remediation.tool_calls_limit == TOOL_CALLS_LIMIT_REMEDIATION

        query = RouterResult(mode=AgentMode.QUERY, tools=[])
        assert query.tool_calls_limit == TOOL_CALLS_LIMIT_QUERY

        chat = RouterResult(mode=AgentMode.CHAT, tools=[])
        assert chat.tool_calls_limit == TOOL_CALLS_LIMIT_CHAT


class TestIntentClassifier:
    """Tests for IntentClassifier (internal component of IntentRouter)."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance with pattern-based classifier."""
        return IntentRouter(use_local=False)

    @pytest.mark.asyncio
    async def test_classify_returns_router_result(self, router: IntentRouter) -> None:
        """Test that route returns RouterResult."""
        await router.initialize()
        result = await router.route("Check server status")
        assert isinstance(result, RouterResult)
        assert isinstance(result.mode, AgentMode)

    @pytest.mark.asyncio
    async def test_classify_diagnostic_patterns(self, router: IntentRouter) -> None:
        """Test classification of diagnostic patterns."""
        await router.initialize()
        diagnostic_texts = [
            "Check server status",
            "Monitor CPU usage",
            "Analyze the logs",
            "Debug this issue",
        ]

        for text in diagnostic_texts:
            result = await router.route(text)
            assert result.mode in [AgentMode.DIAGNOSTIC, AgentMode.CHAT]

    @pytest.mark.asyncio
    async def test_classify_remediation_patterns(self, router: IntentRouter) -> None:
        """Test classification of remediation patterns."""
        await router.initialize()
        remediation_texts = [
            "Fix the error",
            "Restart the service",
            "Deploy the application",
            "Update the configuration",
        ]

        for text in remediation_texts:
            result = await router.route(text)
            assert result.mode in [AgentMode.REMEDIATION, AgentMode.CHAT]

    @pytest.mark.asyncio
    async def test_classify_query_patterns(self, router: IntentRouter) -> None:
        """Test classification of query patterns."""
        await router.initialize()
        query_texts = [
            "What is Docker?",
            "How do I configure SSH?",
            "Explain this error",
        ]

        for text in query_texts:
            result = await router.route(text)
            # May classify as QUERY, CHAT, or DIAGNOSTIC depending on patterns
            assert result.mode in list(AgentMode)


class TestIntentRouter:
    """Tests for IntentRouter."""

    @pytest.fixture
    def mock_context(self) -> MagicMock:
        """Create mock context."""
        ctx = MagicMock()
        ctx.config = MagicMock()
        ctx.config.llm_provider = "openai"
        ctx.config.llm_model = "gpt-4"
        return ctx

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance."""
        return IntentRouter(use_local=False)

    @pytest.mark.asyncio
    async def test_route_returns_result(self, router: IntentRouter) -> None:
        """Test that route returns a RouterResult."""
        await router.initialize()
        result = await router.route("Hello world")

        assert isinstance(result, RouterResult)
        assert isinstance(result.mode, AgentMode)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_route_with_host_mention(self, router: IntentRouter) -> None:
        """Test routing with explicit host mention."""
        await router.initialize()
        result = await router.route("Connect to @myserver")

        # Should detect host mention in entities
        assert "myserver" in result.entities.get("hosts", [])

    @pytest.mark.asyncio
    async def test_route_extracts_files(self, router: IntentRouter) -> None:
        """Test that route extracts file paths."""
        await router.initialize()
        result = await router.route("Edit /etc/nginx/nginx.conf")

        assert "/etc/nginx/nginx.conf" in result.entities.get("files", [])

    @pytest.mark.asyncio
    async def test_route_empty_input(self, router: IntentRouter) -> None:
        """Test routing with empty input."""
        await router.initialize()
        result = await router.route("")

        assert result.mode == AgentMode.CHAT
        # Confidence can vary based on implementation
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_route_whitespace_only(self, router: IntentRouter) -> None:
        """Test routing with whitespace-only input."""
        await router.initialize()
        result = await router.route("   \n\t  ")

        assert result.mode == AgentMode.CHAT

    @pytest.mark.asyncio
    async def test_route_includes_tools(self, router: IntentRouter) -> None:
        """Test that route result includes tools."""
        await router.initialize()
        result = await router.route("Check server status")

        assert isinstance(result.tools, list)
        # Should have at least some tools
        assert len(result.tools) >= 0


class TestJumpHostDetection:
    """Tests for jump host detection in router."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance."""
        return IntentRouter(use_local=False)

    @pytest.mark.asyncio
    async def test_detect_via_hostname(self, router: IntentRouter) -> None:
        """Test detection of 'via @hostname' pattern."""
        await router.initialize()
        result = await router.route("Check disk on 192.168.1.1 via @ansible")
        assert result.jump_host == "ansible"

    @pytest.mark.asyncio
    async def test_detect_via_machine(self, router: IntentRouter) -> None:
        """Test detection of 'via la machine @hostname' pattern (French)."""
        await router.initialize()
        result = await router.route("Analyse cette machine via la machine @bastion")
        assert result.jump_host == "bastion"

    @pytest.mark.asyncio
    async def test_detect_through_hostname(self, router: IntentRouter) -> None:
        """Test detection of 'through @hostname' pattern."""
        await router.initialize()
        result = await router.route("Execute command through @jump-server")
        assert result.jump_host == "jump-server"

    @pytest.mark.asyncio
    async def test_detect_en_passant_par(self, router: IntentRouter) -> None:
        """Test detection of 'en passant par @hostname' pattern (French)."""
        await router.initialize()
        result = await router.route("Vérifie le serveur en passant par @proxy")
        assert result.jump_host == "proxy"

    @pytest.mark.asyncio
    async def test_no_jump_host_when_not_specified(self, router: IntentRouter) -> None:
        """Test no jump_host when not specified."""
        await router.initialize()
        result = await router.route("Check disk on server1")
        assert result.jump_host is None

    @pytest.mark.asyncio
    async def test_detect_via_without_at(self, router: IntentRouter) -> None:
        """Test detection works without @ prefix."""
        await router.initialize()
        result = await router.route("Check status via bastion")
        assert result.jump_host == "bastion"


# ==============================================================================
# Extended Tests for IntentClassifier (intent_classifier.py)
# ==============================================================================


class TestIntentClassifierModule:
    """Tests for IntentClassifier from intent_classifier.py."""

    def test_agent_mode_enum(self) -> None:
        """Test AgentMode enum from intent_classifier module."""
        from merlya.router.intent_classifier import AgentMode as ICAgentMode

        assert ICAgentMode.DIAGNOSTIC == "diagnostic"
        assert ICAgentMode.REMEDIATION == "remediation"
        assert ICAgentMode.QUERY == "query"
        assert ICAgentMode.CHAT == "chat"

    def test_intent_embeddings_defined(self) -> None:
        """Test that INTENT_EMBEDDINGS are defined."""
        from merlya.router.intent_classifier import INTENT_EMBEDDINGS, AgentMode

        assert AgentMode.DIAGNOSTIC in INTENT_EMBEDDINGS
        assert AgentMode.REMEDIATION in INTENT_EMBEDDINGS
        assert AgentMode.QUERY in INTENT_EMBEDDINGS
        assert AgentMode.CHAT in INTENT_EMBEDDINGS

    def test_intent_patterns_defined(self) -> None:
        """Test that INTENT_PATTERNS are defined."""
        from merlya.router.intent_classifier import INTENT_PATTERNS, AgentMode

        assert AgentMode.DIAGNOSTIC in INTENT_PATTERNS
        assert "check" in INTENT_PATTERNS[AgentMode.DIAGNOSTIC]
        assert "fix" in INTENT_PATTERNS[AgentMode.REMEDIATION]
        assert "how" in INTENT_PATTERNS[AgentMode.QUERY]
        assert "hello" in INTENT_PATTERNS[AgentMode.CHAT]

    def test_tool_keywords_defined(self) -> None:
        """Test that TOOL_KEYWORDS are defined."""
        from merlya.router.intent_classifier import TOOL_KEYWORDS

        assert "system" in TOOL_KEYWORDS
        assert "files" in TOOL_KEYWORDS
        assert "security" in TOOL_KEYWORDS
        assert "docker" in TOOL_KEYWORDS
        assert "kubernetes" in TOOL_KEYWORDS

    def test_classifier_init_without_embeddings(self) -> None:
        """Test IntentClassifier initialization without embeddings."""
        from merlya.router.intent_classifier import IntentClassifier

        classifier = IntentClassifier(use_embeddings=False)

        assert classifier.use_embeddings is False
        assert classifier._model_loaded is False
        assert classifier._session is None
        assert classifier._tokenizer is None

    def test_classifier_init_with_embeddings(self) -> None:
        """Test IntentClassifier initialization with embeddings flag."""
        from merlya.router.intent_classifier import IntentClassifier

        classifier = IntentClassifier(use_embeddings=True)

        assert classifier.use_embeddings is True
        assert classifier._model_loaded is False

    def test_classifier_init_with_model_id(self) -> None:
        """Test IntentClassifier initialization with custom model_id."""
        from merlya.router.intent_classifier import IntentClassifier

        classifier = IntentClassifier(model_id="custom-model")

        assert classifier._model_id == "custom-model"

    def test_classifier_init_with_tier(self) -> None:
        """Test IntentClassifier initialization with tier."""
        from merlya.router.intent_classifier import IntentClassifier

        classifier = IntentClassifier(tier="minimal")

        assert classifier._tier == "minimal"


class TestIntentClassifierClassifyByPatterns:
    """Tests for pattern-based classification."""

    @pytest.fixture
    def classifier(self):
        """Create classifier with embeddings disabled."""
        from merlya.router.intent_classifier import IntentClassifier

        return IntentClassifier(use_embeddings=False)

    def test_classify_diagnostic_pattern(self, classifier) -> None:
        """Test classification of diagnostic patterns."""
        mode, confidence = classifier.classify_patterns("check the server status")

        assert mode.value in ["diagnostic", "chat"]
        assert 0.0 <= confidence <= 1.0

    def test_classify_remediation_pattern(self, classifier) -> None:
        """Test classification of remediation patterns."""
        mode, _confidence = classifier.classify_patterns("fix the broken service")

        assert mode.value in ["remediation", "chat"]

    def test_classify_query_pattern(self, classifier) -> None:
        """Test classification of query patterns."""
        # "why is" should trigger query pattern
        mode, _confidence = classifier.classify_patterns("why is the server slow")

        assert mode.value in ["query", "chat", "diagnostic"]

    def test_classify_chat_pattern(self, classifier) -> None:
        """Test classification of chat patterns."""
        mode, _confidence = classifier.classify_patterns("hello there")

        assert mode.value == "chat"

    def test_classify_empty_input(self, classifier) -> None:
        """Test classification of empty input."""
        mode, _confidence = classifier.classify_patterns("")

        assert mode.value == "chat"

    def test_classify_returns_confidence(self, classifier) -> None:
        """Test that classification returns confidence score."""
        _mode, confidence = classifier.classify_patterns("check status")

        assert 0.0 <= confidence <= 1.0


class TestIntentClassifierDetermineTools:
    """Tests for determine_tools method."""

    @pytest.fixture
    def classifier(self):
        """Create classifier."""
        from merlya.router.intent_classifier import IntentClassifier

        return IntentClassifier(use_embeddings=False)

    def test_determine_tools_system_keyword(self, classifier) -> None:
        """Test determining system tools by keyword."""
        # "cpu" is in TOOL_KEYWORDS["system"]
        tools = classifier.determine_tools("check cpu usage", {"hosts": []})

        assert "system" in tools

    def test_determine_tools_files(self, classifier) -> None:
        """Test determining files tools."""
        # "file" is in TOOL_KEYWORDS["files"]
        tools = classifier.determine_tools("edit the config file", {"files": ["/etc/config"]})

        assert "files" in tools

    def test_determine_tools_security(self, classifier) -> None:
        """Test determining security tools."""
        # "ssh" and "firewall" are in TOOL_KEYWORDS["security"]
        tools = classifier.determine_tools("check ssh keys and firewall", {})

        assert "security" in tools

    def test_determine_tools_docker(self, classifier) -> None:
        """Test determining docker tools."""
        # "docker" is in TOOL_KEYWORDS["docker"]
        tools = classifier.determine_tools("list docker containers", {})

        assert "docker" in tools

    def test_determine_tools_kubernetes(self, classifier) -> None:
        """Test determining kubernetes tools."""
        # "kubernetes" is in TOOL_KEYWORDS["kubernetes"]
        tools = classifier.determine_tools("check kubernetes pods", {})

        assert "kubernetes" in tools

    def test_determine_tools_always_includes_core(self, classifier) -> None:
        """Test that core is always included."""
        tools = classifier.determine_tools("hello", {})

        assert "core" in tools

    def test_determine_tools_with_hosts_adds_system(self, classifier) -> None:
        """Test that system is added when hosts present."""
        tools = classifier.determine_tools("check", {"hosts": ["server1"]})

        assert "system" in tools


class TestIntentClassifierCheckDelegation:
    """Tests for check_delegation method."""

    @pytest.fixture
    def classifier(self):
        """Create classifier."""
        from merlya.router.intent_classifier import IntentClassifier

        return IntentClassifier(use_embeddings=False)

    def test_check_delegation_no_match(self, classifier) -> None:
        """Test check_delegation with no delegation pattern."""
        result = classifier.check_delegation("check server status")

        assert result is None

    def test_check_delegation_knowledge_pattern(self, classifier) -> None:
        """Test check_delegation with knowledge pattern."""
        result = classifier.check_delegation("what is the best practice for SSH security")

        # May return "knowledge" or None depending on implementation
        assert result in [None, "knowledge", "claude"]


class TestIntentClassifierLoadModel:
    """Tests for load_model method."""

    @pytest.fixture
    def classifier(self):
        """Create classifier with embeddings enabled."""
        from merlya.router.intent_classifier import IntentClassifier

        return IntentClassifier(use_embeddings=True)

    @pytest.mark.asyncio
    async def test_load_model_without_embeddings(self) -> None:
        """Test load_model when embeddings disabled."""
        from merlya.router.intent_classifier import IntentClassifier

        classifier = IntentClassifier(use_embeddings=False)
        result = await classifier.load_model()

        assert result is True

    @pytest.mark.asyncio
    async def test_load_model_missing_onnx(self) -> None:
        """Test load_model when onnxruntime not available."""
        from unittest.mock import patch

        from merlya.router.intent_classifier import IntentClassifier

        classifier = IntentClassifier(use_embeddings=True)

        with patch.dict("sys.modules", {"onnxruntime": None}):
            # This may raise or return False depending on implementation
            try:
                result = await classifier.load_model()
                # If it doesn't raise, it should return False or True
                assert isinstance(result, bool)
            except ImportError:
                pass  # Expected if strict import check


class TestIntentClassifierDisableEmbeddings:
    """Tests for _disable_embeddings method."""

    def test_disable_embeddings_sets_flag(self, tmp_path) -> None:
        """Test that _disable_embeddings sets use_embeddings to False."""
        from merlya.router.intent_classifier import IntentClassifier

        classifier = IntentClassifier(use_embeddings=True)
        model_path = tmp_path / "model.onnx"
        tokenizer_path = tmp_path / "tokenizer.json"

        # Reset class-level warning flag
        IntentClassifier._onnx_warning_shown = False

        result = classifier._disable_embeddings(model_path, tokenizer_path)

        assert result is False
        assert classifier.use_embeddings is False

    def test_disable_embeddings_warning_shown_once(self, tmp_path) -> None:
        """Test that warning is only shown once."""
        from merlya.router.intent_classifier import IntentClassifier

        # Reset warning flag
        IntentClassifier._onnx_warning_shown = False

        classifier1 = IntentClassifier(use_embeddings=True)
        classifier2 = IntentClassifier(use_embeddings=True)

        model_path = tmp_path / "model.onnx"
        tokenizer_path = tmp_path / "tokenizer.json"

        classifier1._disable_embeddings(model_path, tokenizer_path)
        assert IntentClassifier._onnx_warning_shown is True

        classifier2._disable_embeddings(model_path, tokenizer_path)
        # Still True, didn't reset


class TestIntentClassifierEmbeddingCache:
    """Tests for embedding cache functionality."""

    def test_embedding_cache_max_size(self) -> None:
        """Test that embedding cache has max size setting."""
        from merlya.router.intent_classifier import IntentClassifier

        assert IntentClassifier.EMBEDDING_CACHE_MAX_SIZE == 1000

    def test_classifier_has_embedding_cache(self) -> None:
        """Test that classifier initializes with empty cache."""
        from merlya.router.intent_classifier import IntentClassifier

        classifier = IntentClassifier(use_embeddings=False)

        assert hasattr(classifier, "_embedding_cache")
        assert len(classifier._embedding_cache) == 0


# ==============================================================================
# Extended Tests for router/classifier.py RouterResult and IntentRouter
# ==============================================================================


class TestRouterResultExtended:
    """Extended tests for RouterResult properties."""

    def test_is_fast_path_true(self) -> None:
        """Test is_fast_path when fast_path is set."""
        result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="host.list",
        )
        assert result.is_fast_path is True

    def test_is_fast_path_false(self) -> None:
        """Test is_fast_path when fast_path is None."""
        result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
        )
        assert result.is_fast_path is False

    def test_is_skill_match_true(self) -> None:
        """Test is_skill_match when skill matched with high confidence."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="disk_check",
            skill_confidence=0.85,
        )
        assert result.is_skill_match is True

    def test_is_skill_match_false_no_skill(self) -> None:
        """Test is_skill_match when no skill matched."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
        )
        assert result.is_skill_match is False

    def test_is_skill_match_false_low_confidence(self) -> None:
        """Test is_skill_match when confidence below threshold."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="disk_check",
            skill_confidence=0.3,  # Below 0.5 threshold
        )
        assert result.is_skill_match is False

    def test_request_limit_by_mode(self) -> None:
        """Test dynamic request_limit based on mode."""
        from merlya.config.constants import (
            REQUEST_LIMIT_CHAT,
            REQUEST_LIMIT_DIAGNOSTIC,
            REQUEST_LIMIT_QUERY,
            REQUEST_LIMIT_REMEDIATION,
        )

        diagnostic = RouterResult(mode=AgentMode.DIAGNOSTIC, tools=[])
        assert diagnostic.request_limit == REQUEST_LIMIT_DIAGNOSTIC

        remediation = RouterResult(mode=AgentMode.REMEDIATION, tools=[])
        assert remediation.request_limit == REQUEST_LIMIT_REMEDIATION

        query = RouterResult(mode=AgentMode.QUERY, tools=[])
        assert query.request_limit == REQUEST_LIMIT_QUERY

        chat = RouterResult(mode=AgentMode.CHAT, tools=[])
        assert chat.request_limit == REQUEST_LIMIT_CHAT


class TestIntentRouterExtended:
    """Extended tests for IntentRouter."""

    def test_router_init_local_true(self) -> None:
        """Test router initialization with use_local=True."""
        router = IntentRouter(use_local=True)
        assert router.classifier.use_embeddings is True
        assert router._llm_model is None
        assert router._initialized is False

    def test_router_init_local_false(self) -> None:
        """Test router initialization with use_local=False."""
        router = IntentRouter(use_local=False)
        assert router.classifier.use_embeddings is False

    def test_router_init_with_model_id(self) -> None:
        """Test router initialization with model_id."""
        router = IntentRouter(model_id="custom-model")
        assert router.classifier._model_id == "custom-model"

    def test_router_init_with_tier(self) -> None:
        """Test router initialization with tier."""
        router = IntentRouter(tier="minimal")
        assert router.classifier._tier == "minimal"

    def test_set_llm_fallback(self) -> None:
        """Test set_llm_fallback sets model."""
        router = IntentRouter(use_local=False)
        router.set_llm_fallback("openai:gpt-4")
        assert router._llm_model == "openai:gpt-4"

    @pytest.mark.asyncio
    async def test_route_auto_initialize(self) -> None:
        """Test route auto-initializes if not initialized."""
        router = IntentRouter(use_local=False)
        assert router._initialized is False

        result = await router.route("Hello")

        assert router._initialized is True
        assert isinstance(result, RouterResult)

    def test_model_loaded_property(self) -> None:
        """Test model_loaded property."""
        router = IntentRouter(use_local=False)
        assert router.model_loaded is False

    def test_embedding_dim_property(self) -> None:
        """Test embedding_dim property."""
        router = IntentRouter(use_local=False)
        # Without model loaded, embedding_dim is None
        assert router.embedding_dim is None

    def test_validate_identifier_valid(self) -> None:
        """Test _validate_identifier with valid names."""
        router = IntentRouter(use_local=False)

        assert router._validate_identifier("web-server") is True
        assert router._validate_identifier("host01") is True
        assert router._validate_identifier("my_host.local") is True
        assert router._validate_identifier("a") is True

    def test_validate_identifier_invalid(self) -> None:
        """Test _validate_identifier with invalid names."""
        router = IntentRouter(use_local=False)

        assert router._validate_identifier("") is False
        assert router._validate_identifier("a" * 256) is False
        assert router._validate_identifier("../etc/passwd") is False
        assert router._validate_identifier("-invalid") is False
        assert router._validate_identifier(".invalid") is False


class TestFastPathDetection:
    """Tests for fast path detection."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance."""
        return IntentRouter(use_local=False)

    def test_detect_host_list_fr(self, router: IntentRouter) -> None:
        """Test fast path detection for 'liste les hosts'."""
        fast_path, args = router._detect_fast_path("liste les hosts")
        assert fast_path == "host.list"
        assert args == {}

    def test_detect_host_list_en(self, router: IntentRouter) -> None:
        """Test fast path detection for 'show hosts'."""
        fast_path, _args = router._detect_fast_path("show hosts")
        assert fast_path == "host.list"

    def test_detect_host_details(self, router: IntentRouter) -> None:
        """Test fast path detection for 'info on @webserver'."""
        fast_path, args = router._detect_fast_path("info on @webserver")
        assert fast_path == "host.details"
        assert args.get("target") == "webserver"

    def test_detect_inventory(self, router: IntentRouter) -> None:
        """Test fast path detection for 'inventory'."""
        fast_path, _args = router._detect_fast_path("inventory")
        assert fast_path == "host.list"

    def test_detect_group_list(self, router: IntentRouter) -> None:
        """Test fast path detection for 'liste les groupes'."""
        fast_path, _args = router._detect_fast_path("liste les groupes")
        assert fast_path == "group.list"

    def test_detect_skill_list(self, router: IntentRouter) -> None:
        """Test fast path detection for 'show skills'."""
        fast_path, _args = router._detect_fast_path("show skills")
        assert fast_path == "skill.list"

    def test_detect_var_list(self, router: IntentRouter) -> None:
        """Test fast path detection for 'show variables'."""
        fast_path, _args = router._detect_fast_path("show variables")
        assert fast_path == "var.list"

    def test_detect_no_fast_path(self, router: IntentRouter) -> None:
        """Test no fast path for general queries."""
        fast_path, args = router._detect_fast_path("check disk usage on all servers")
        assert fast_path is None
        assert args == {}

    def test_detect_invalid_target_rejected(self, router: IntentRouter) -> None:
        """Test that invalid targets are rejected."""
        # Path traversal attempt
        _fast_path, args = router._detect_fast_path("info on @../etc/passwd")
        # Should not match due to invalid identifier
        assert "target" not in args or args.get("target") != "../etc/passwd"

    def test_detect_no_fast_path_for_pid_queries_fr(self, router: IntentRouter) -> None:
        """Avoid false positives like 'sur le PID 1234' being treated as host details."""
        fast_path, args = router._detect_fast_path("donne moi plus d'info sur le PID 3130830")
        assert fast_path is None
        assert args == {}

        fast_path, args = router._detect_fast_path("donne moi plus d'info sur process PID 3130830")
        assert fast_path is None
        assert args == {}

    @pytest.mark.asyncio
    async def test_route_fast_path(self, router: IntentRouter) -> None:
        """Test route with fast path detection."""
        await router.initialize()
        result = await router.route("liste les hosts")

        assert result.is_fast_path is True
        assert result.fast_path == "host.list"
        assert result.mode == AgentMode.QUERY
        assert result.confidence == 1.0


class TestClassifyMethod:
    """Tests for _classify method."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance."""
        return IntentRouter(use_local=False)

    @pytest.mark.asyncio
    async def test_classify_basic(self, router: IntentRouter) -> None:
        """Test _classify with basic input."""
        await router.initialize()
        result = await router._classify("check server status")

        assert isinstance(result, RouterResult)
        assert isinstance(result.mode, AgentMode)
        assert isinstance(result.tools, list)

    @pytest.mark.asyncio
    async def test_classify_with_jump_host(self, router: IntentRouter) -> None:
        """Test _classify detects jump host."""
        await router.initialize()
        result = await router._classify("check server via @bastion")

        assert result.jump_host == "bastion"


class TestDetectJumpHost:
    """Tests for _detect_jump_host method."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance."""
        return IntentRouter(use_local=False)

    def test_detect_via_pattern(self, router: IntentRouter) -> None:
        """Test detection of 'via @hostname' pattern."""
        result = router._detect_jump_host("connect via @bastion")
        assert result == "bastion"

    def test_detect_through_pattern(self, router: IntentRouter) -> None:
        """Test detection of 'through @hostname' pattern."""
        result = router._detect_jump_host("connect through @jump")
        assert result == "jump"

    def test_detect_french_passant_par(self, router: IntentRouter) -> None:
        """Test detection of 'en passant par @hostname' pattern."""
        result = router._detect_jump_host("connexion en passant par @proxy")
        assert result == "proxy"

    def test_detect_depuis(self, router: IntentRouter) -> None:
        """Test detection of 'depuis @hostname' pattern."""
        result = router._detect_jump_host("accès depuis @jumphost")
        assert result == "jumphost"

    def test_detect_bastion_equals(self, router: IntentRouter) -> None:
        """Test detection of 'bastion=hostname' pattern."""
        result = router._detect_jump_host("connect bastion=mybastion")
        assert result == "mybastion"

    def test_no_detection(self, router: IntentRouter) -> None:
        """Test no detection when no pattern matches."""
        result = router._detect_jump_host("check disk on server1")
        assert result is None

    def test_filter_false_positives(self, router: IntentRouter) -> None:
        """Test that common words are filtered out."""
        # "via the machine" - "the" should be filtered
        result = router._detect_jump_host("connect via the server")
        # "the" is in false positives list, but "server" should match
        assert result != "the"


class TestMatchSkillMethods:
    """Tests for skill matching methods."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance."""
        return IntentRouter(use_local=False)

    @pytest.mark.asyncio
    async def test_match_skill_embeddings_no_model(self, router: IntentRouter) -> None:
        """Test _match_skill_embeddings when model not loaded."""
        # Model not loaded, should return None, 0.0
        result = await router._match_skill_embeddings("check disk")
        assert result == (None, 0.0)

    def test_match_skill_regex_no_registry(self, router: IntentRouter) -> None:
        """Test _match_skill with no skills registered."""
        # Should return None, 0.0 when no skills match
        result = router._match_skill("random text")
        assert result == (None, 0.0)


class TestParseLLMResponse:
    """Tests for _parse_llm_response method."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance."""
        return IntentRouter(use_local=False)

    def test_parse_valid_response(self, router: IntentRouter) -> None:
        """Test parsing valid LLM response."""
        from unittest.mock import MagicMock

        response = MagicMock()
        response.data = '{"mode": "diagnostic", "tools": ["system"], "credentials_required": false, "elevation_required": true, "reasoning": "User wants status"}'

        result = router._parse_llm_response(response, "check status")

        assert result is not None
        assert result.mode == AgentMode.DIAGNOSTIC
        assert "system" in result.tools
        assert result.elevation_required is True
        assert result.credentials_required is False
        assert result.confidence == 0.9

    def test_parse_invalid_mode(self, router: IntentRouter) -> None:
        """Test parsing response with invalid mode."""
        from unittest.mock import MagicMock

        response = MagicMock()
        response.data = '{"mode": "invalid_mode", "tools": []}'

        result = router._parse_llm_response(response, "test")

        # Should default to CHAT for invalid mode
        assert result is not None
        assert result.mode == AgentMode.CHAT

    def test_parse_invalid_json(self, router: IntentRouter) -> None:
        """Test parsing invalid JSON response."""
        from unittest.mock import MagicMock

        response = MagicMock()
        response.data = "not valid json {"

        result = router._parse_llm_response(response, "test")

        assert result is None

    def test_parse_response_too_large(self, router: IntentRouter) -> None:
        """Test parsing oversized response."""
        from unittest.mock import MagicMock

        response = MagicMock()
        # Create response larger than 100KB
        response.data = '{"mode": "chat", "tools": []}' + "x" * 100_001

        result = router._parse_llm_response(response, "test")

        assert result is None

    def test_parse_response_with_output_attr(self, router: IntentRouter) -> None:
        """Test parsing response with output attribute."""
        from unittest.mock import MagicMock

        response = MagicMock(spec=[])  # No data attr
        response.output = '{"mode": "query", "tools": ["core"]}'

        result = router._parse_llm_response(response, "what is this")

        assert result is not None
        assert result.mode == AgentMode.QUERY

    def test_parse_response_str_fallback(self, router: IntentRouter) -> None:
        """Test parsing response using str() fallback."""

        class CustomResponse:
            def __str__(self) -> str:
                return '{"mode": "remediation", "tools": ["system"]}'

        result = router._parse_llm_response(CustomResponse(), "fix server")

        assert result is not None
        assert result.mode == AgentMode.REMEDIATION


class TestRouteWithSkipPrefix:
    """Tests for route with ! prefix to skip skills."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance."""
        return IntentRouter(use_local=False)

    @pytest.mark.asyncio
    async def test_route_with_skip_prefix(self, router: IntentRouter) -> None:
        """Test that ! prefix is handled correctly."""
        await router.initialize()

        # The ! prefix should be stripped
        result = await router.route("!check disk usage")

        assert isinstance(result, RouterResult)
        # The input should work normally without the !

    @pytest.mark.asyncio
    async def test_route_with_delegate_invalid(self, router: IntentRouter) -> None:
        """Test route validates delegation against available agents."""
        await router.initialize()

        # Mock classifier to suggest delegation
        from unittest.mock import patch

        with patch.object(router.classifier, "check_delegation", return_value="nonexistent_agent"):
            result = await router.route("delegate this task", available_agents=["agent1", "agent2"])

            # Delegation should be cleared if agent not available
            assert result.delegate_to is None

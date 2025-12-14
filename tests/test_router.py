"""
Tests for router module (intent classification and routing).
"""

import pytest

from merlya.router.classifier import (
    _COMPILED_FAST_PATH,
    FAST_PATH_INTENTS,
    FAST_PATH_PATTERNS,
    IntentRouter,
    RouterResult,
)
from merlya.router.intent_classifier import (
    INTENT_PATTERNS,
    TOOL_KEYWORDS,
    AgentMode,
    IntentClassifier,
)


class TestAgentMode:
    """Tests for AgentMode enum."""

    def test_mode_values(self):
        """Test enum has expected values."""
        assert AgentMode.DIAGNOSTIC.value == "diagnostic"
        assert AgentMode.REMEDIATION.value == "remediation"
        assert AgentMode.QUERY.value == "query"
        assert AgentMode.CHAT.value == "chat"

    def test_mode_from_string(self):
        """Test creating mode from string."""
        assert AgentMode("diagnostic") == AgentMode.DIAGNOSTIC
        assert AgentMode("remediation") == AgentMode.REMEDIATION
        assert AgentMode("query") == AgentMode.QUERY
        assert AgentMode("chat") == AgentMode.CHAT

    def test_mode_invalid_raises(self):
        """Test invalid mode string raises ValueError."""
        with pytest.raises(ValueError):
            AgentMode("invalid")


class TestIntentPatterns:
    """Tests for intent pattern matching."""

    def test_diagnostic_patterns_exist(self):
        """Test diagnostic patterns are defined."""
        assert AgentMode.DIAGNOSTIC in INTENT_PATTERNS
        assert "check" in INTENT_PATTERNS[AgentMode.DIAGNOSTIC]
        assert "status" in INTENT_PATTERNS[AgentMode.DIAGNOSTIC]
        assert "monitor" in INTENT_PATTERNS[AgentMode.DIAGNOSTIC]

    def test_remediation_patterns_exist(self):
        """Test remediation patterns are defined."""
        assert AgentMode.REMEDIATION in INTENT_PATTERNS
        assert "fix" in INTENT_PATTERNS[AgentMode.REMEDIATION]
        assert "restart" in INTENT_PATTERNS[AgentMode.REMEDIATION]
        assert "deploy" in INTENT_PATTERNS[AgentMode.REMEDIATION]

    def test_query_patterns_exist(self):
        """Test query patterns are defined."""
        assert AgentMode.QUERY in INTENT_PATTERNS
        assert "how" in INTENT_PATTERNS[AgentMode.QUERY]
        assert "why" in INTENT_PATTERNS[AgentMode.QUERY]
        assert "explain" in INTENT_PATTERNS[AgentMode.QUERY]

    def test_chat_patterns_exist(self):
        """Test chat patterns are defined."""
        assert AgentMode.CHAT in INTENT_PATTERNS
        assert "hello" in INTENT_PATTERNS[AgentMode.CHAT]
        assert "thanks" in INTENT_PATTERNS[AgentMode.CHAT]


class TestToolKeywords:
    """Tests for tool keyword configuration."""

    def test_system_keywords(self):
        """Test system tool keywords."""
        assert "system" in TOOL_KEYWORDS
        assert "cpu" in TOOL_KEYWORDS["system"]
        assert "memory" in TOOL_KEYWORDS["system"]
        assert "disk" in TOOL_KEYWORDS["system"]

    def test_files_keywords(self):
        """Test files tool keywords."""
        assert "files" in TOOL_KEYWORDS
        assert "file" in TOOL_KEYWORDS["files"]
        assert "log" in TOOL_KEYWORDS["files"]
        assert "config" in TOOL_KEYWORDS["files"]

    def test_security_keywords(self):
        """Test security tool keywords."""
        assert "security" in TOOL_KEYWORDS
        assert "port" in TOOL_KEYWORDS["security"]
        assert "firewall" in TOOL_KEYWORDS["security"]
        assert "ssh" in TOOL_KEYWORDS["security"]


class TestIntentClassifier:
    """Tests for IntentClassifier."""

    def test_classifier_init_without_embeddings(self):
        """Test classifier initialization without embeddings."""
        classifier = IntentClassifier(use_embeddings=False)
        assert classifier.use_embeddings is False
        assert classifier._model_loaded is False

    def test_classify_patterns_diagnostic(self):
        """Test pattern classification for diagnostic intent."""
        classifier = IntentClassifier(use_embeddings=False)
        mode, confidence = classifier.classify_patterns("check the server status")
        assert mode == AgentMode.DIAGNOSTIC
        assert confidence > 0

    def test_classify_patterns_remediation(self):
        """Test pattern classification for remediation intent."""
        classifier = IntentClassifier(use_embeddings=False)
        mode, confidence = classifier.classify_patterns("restart the nginx service")
        assert mode == AgentMode.REMEDIATION
        assert confidence > 0

    def test_classify_patterns_query(self):
        """Test pattern classification for query intent."""
        classifier = IntentClassifier(use_embeddings=False)
        # Use a clear query without remediation keywords
        mode, confidence = classifier.classify_patterns("explain how ssh works")
        assert mode == AgentMode.QUERY
        assert confidence > 0

    def test_classify_patterns_chat(self):
        """Test pattern classification for chat intent."""
        classifier = IntentClassifier(use_embeddings=False)
        mode, confidence = classifier.classify_patterns("hello")
        assert mode == AgentMode.CHAT
        assert confidence > 0

    def test_classify_patterns_no_match_defaults_to_chat(self):
        """Test that no match defaults to chat mode."""
        classifier = IntentClassifier(use_embeddings=False)
        mode, confidence = classifier.classify_patterns("xyzzy")
        assert mode == AgentMode.CHAT
        assert confidence == 0.5  # Default confidence

    def test_extract_entities_hosts(self):
        """Test entity extraction for hosts."""
        classifier = IntentClassifier(use_embeddings=False)
        entities = classifier.extract_entities("check @web-01 and @db-server")
        assert "web-01" in entities["hosts"]
        assert "db-server" in entities["hosts"]

    def test_extract_entities_variables(self):
        """Test entity extraction for variables."""
        classifier = IntentClassifier(use_embeddings=False)
        entities = classifier.extract_entities("use @MY_VAR and @config_value")
        assert "MY_VAR" in entities["variables"]
        assert "config_value" in entities["variables"]

    def test_extract_entities_mixedcase_treated_as_variable(self):
        """CamelCase or mixed-case mentions should not be treated as hosts."""
        classifier = IntentClassifier(use_embeddings=False)
        entities = classifier.extract_entities("quel est la valeur de @MotDePasseTopSecret")
        assert "MotDePasseTopSecret" in entities["variables"]
        assert "MotDePasseTopSecret" not in entities["hosts"]

    def test_extract_entities_files(self):
        """Test entity extraction for file paths."""
        classifier = IntentClassifier(use_embeddings=False)
        entities = classifier.extract_entities("read /etc/nginx/nginx.conf and ~/config.yaml")
        assert "/etc/nginx/nginx.conf" in entities["files"]
        assert "~/config.yaml" in entities["files"]

    def test_determine_tools_system(self):
        """Test tool determination for system."""
        classifier = IntentClassifier(use_embeddings=False)
        tools = classifier.determine_tools("check cpu usage", {})
        assert "core" in tools
        assert "system" in tools

    def test_determine_tools_files(self):
        """Test tool determination for files."""
        classifier = IntentClassifier(use_embeddings=False)
        tools = classifier.determine_tools("read the log file", {})
        assert "core" in tools
        assert "files" in tools

    def test_determine_tools_security(self):
        """Test tool determination for security."""
        classifier = IntentClassifier(use_embeddings=False)
        tools = classifier.determine_tools("check ssh configuration", {})
        assert "core" in tools
        assert "security" in tools

    def test_determine_tools_with_hosts(self):
        """Test tool determination adds system for hosts."""
        classifier = IntentClassifier(use_embeddings=False)
        tools = classifier.determine_tools("hello", {"hosts": ["web-01"]})
        assert "system" in tools

    def test_check_delegation_docker(self):
        """Test delegation check for docker."""
        classifier = IntentClassifier(use_embeddings=False)
        delegate = classifier.check_delegation("list docker containers")
        assert delegate == "docker"

    def test_check_delegation_kubernetes(self):
        """Test delegation check for kubernetes."""
        classifier = IntentClassifier(use_embeddings=False)
        delegate = classifier.check_delegation("kubectl get pods")
        assert delegate == "kubernetes"

    def test_check_delegation_none(self):
        """Test delegation check returns None for normal input."""
        classifier = IntentClassifier(use_embeddings=False)
        delegate = classifier.check_delegation("check server status")
        assert delegate is None


class TestFastPath:
    """Tests for fast path intent detection."""

    def test_fast_path_intents_defined(self):
        """Test fast path intents are defined."""
        assert "host.list" in FAST_PATH_INTENTS
        assert "host.details" in FAST_PATH_INTENTS
        assert "group.list" in FAST_PATH_INTENTS

    def test_fast_path_patterns_compiled(self):
        """Test fast path patterns are pre-compiled."""
        assert len(_COMPILED_FAST_PATH) > 0
        for intent in FAST_PATH_PATTERNS:
            assert intent in _COMPILED_FAST_PATH

    def test_detect_host_list_english(self):
        """Test host list detection in English."""
        router = IntentRouter(use_local=False)
        intent, _args = router._detect_fast_path("list hosts")
        assert intent == "host.list"

    def test_detect_host_list_french(self):
        """Test host list detection in French."""
        router = IntentRouter(use_local=False)
        intent, _args = router._detect_fast_path("liste les serveurs")
        assert intent == "host.list"

    def test_detect_host_details(self):
        """Test host details detection."""
        router = IntentRouter(use_local=False)
        intent, args = router._detect_fast_path("info on @web-01")
        assert intent == "host.details"
        assert args.get("target") == "web-01"

    def test_detect_host_mention_only(self):
        """Test single host mention detection."""
        router = IntentRouter(use_local=False)
        intent, args = router._detect_fast_path("@web-server")
        assert intent == "host.details"
        assert args.get("target") == "web-server"

    def test_detect_group_list(self):
        """Test group list detection."""
        router = IntentRouter(use_local=False)
        intent, _args = router._detect_fast_path("show groups")
        assert intent == "group.list"

    def test_no_fast_path(self):
        """Test no fast path for complex queries."""
        router = IntentRouter(use_local=False)
        intent, args = router._detect_fast_path("restart nginx on all servers")
        assert intent is None
        assert args == {}


class TestJumpHostDetection:
    """Tests for jump host detection."""

    def test_detect_via_english(self):
        """Test jump host detection with 'via'."""
        router = IntentRouter(use_local=False)
        jump_host = router._detect_jump_host("check status via @bastion")
        assert jump_host == "bastion"

    def test_detect_through_english(self):
        """Test jump host detection with 'through'."""
        router = IntentRouter(use_local=False)
        jump_host = router._detect_jump_host("connect through jump-host")
        assert jump_host == "jump-host"

    def test_detect_via_french(self):
        """Test jump host detection with French 'via'."""
        router = IntentRouter(use_local=False)
        jump_host = router._detect_jump_host("vérifier via @ansible")
        assert jump_host == "ansible"

    def test_detect_en_passant_par(self):
        """Test jump host detection with French 'en passant par'."""
        router = IntentRouter(use_local=False)
        jump_host = router._detect_jump_host("exécuter en passant par bastion-01")
        assert jump_host == "bastion-01"

    def test_no_jump_host(self):
        """Test no jump host for normal queries."""
        router = IntentRouter(use_local=False)
        jump_host = router._detect_jump_host("check server status")
        assert jump_host is None


class TestRouterResult:
    """Tests for RouterResult dataclass."""

    def test_result_defaults(self):
        """Test RouterResult default values."""
        result = RouterResult(mode=AgentMode.DIAGNOSTIC, tools=["core"])
        assert result.confidence == 0.0
        assert result.delegate_to is None
        assert result.jump_host is None
        assert result.fast_path is None
        assert result.skill_match is None

    def test_is_fast_path_true(self):
        """Test is_fast_path property when fast path is set."""
        result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="host.list",
        )
        assert result.is_fast_path is True

    def test_is_fast_path_false(self):
        """Test is_fast_path property when no fast path."""
        result = RouterResult(mode=AgentMode.DIAGNOSTIC, tools=["core"])
        assert result.is_fast_path is False

    def test_is_skill_match_true(self):
        """Test is_skill_match property when skill matched."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="incident_triage",
            skill_confidence=0.8,
        )
        assert result.is_skill_match is True

    def test_is_skill_match_false_low_confidence(self):
        """Test is_skill_match property with low confidence."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="incident_triage",
            skill_confidence=0.3,
        )
        assert result.is_skill_match is False

    def test_tool_calls_limit_diagnostic(self):
        """Test tool calls limit for diagnostic mode."""
        result = RouterResult(mode=AgentMode.DIAGNOSTIC, tools=["core"])
        assert result.tool_calls_limit > 0

    def test_tool_calls_limit_remediation(self):
        """Test tool calls limit for remediation mode."""
        result = RouterResult(mode=AgentMode.REMEDIATION, tools=["core"])
        assert result.tool_calls_limit > 0

    def test_request_limit_by_mode(self):
        """Test request limit varies by mode."""
        diagnostic = RouterResult(mode=AgentMode.DIAGNOSTIC, tools=["core"])
        chat = RouterResult(mode=AgentMode.CHAT, tools=["core"])
        # Diagnostic should have higher limit than chat
        assert diagnostic.request_limit >= chat.request_limit


class TestIntentRouter:
    """Tests for IntentRouter."""

    def test_router_init(self):
        """Test router initialization."""
        router = IntentRouter(use_local=False)
        assert router._initialized is False
        assert router._llm_model is None

    def test_set_llm_fallback(self):
        """Test setting LLM fallback model."""
        router = IntentRouter(use_local=False)
        router.set_llm_fallback("openai:gpt-4o-mini")
        assert router._llm_model == "openai:gpt-4o-mini"

    def test_validate_identifier_valid(self):
        """Test identifier validation for valid names."""
        router = IntentRouter(use_local=False)
        assert router._validate_identifier("web-01") is True
        assert router._validate_identifier("db_server") is True
        assert router._validate_identifier("host.local") is True

    def test_validate_identifier_invalid(self):
        """Test identifier validation for invalid names."""
        router = IntentRouter(use_local=False)
        assert router._validate_identifier("") is False
        assert router._validate_identifier("../etc/passwd") is False
        assert router._validate_identifier("-invalid") is False
        assert router._validate_identifier("a" * 256) is False

    @pytest.mark.asyncio
    async def test_route_fast_path(self):
        """Test routing with fast path detection."""
        router = IntentRouter(use_local=False)
        result = await router.route("list hosts", check_skills=False)
        assert result.is_fast_path is True
        assert result.fast_path == "host.list"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_route_diagnostic(self):
        """Test routing for diagnostic intent."""
        router = IntentRouter(use_local=False)
        result = await router.route("check the server cpu usage", check_skills=False)
        assert result.mode == AgentMode.DIAGNOSTIC
        assert "system" in result.tools

    @pytest.mark.asyncio
    async def test_route_remediation(self):
        """Test routing for remediation intent."""
        router = IntentRouter(use_local=False)
        result = await router.route("restart the nginx service", check_skills=False)
        assert result.mode == AgentMode.REMEDIATION

    @pytest.mark.asyncio
    async def test_route_with_jump_host(self):
        """Test routing with jump host detection."""
        router = IntentRouter(use_local=False)
        result = await router.route("check status via @bastion", check_skills=False)
        assert result.jump_host == "bastion"

    @pytest.mark.asyncio
    async def test_route_extracts_entities(self):
        """Test routing extracts entities."""
        router = IntentRouter(use_local=False)
        result = await router.route("check @web-01 disk usage", check_skills=False)
        assert "web-01" in result.entities.get("hosts", [])


class TestTierIntegration:
    """Tests for tier configuration integration."""

    def test_classifier_uses_tier_config(self):
        """Test classifier uses centralized tier config."""
        classifier = IntentClassifier(use_embeddings=True, tier="balanced")
        model_id = classifier._select_model_id(None, "balanced")

        from merlya.config.tiers import get_router_model_id

        expected = get_router_model_id("balanced")
        assert model_id == expected

    def test_classifier_model_path_uses_tier_config(self):
        """Test classifier model path uses centralized config."""
        classifier = IntentClassifier(use_embeddings=True)

        from merlya.config.tiers import get_router_model_id, resolve_model_path

        model_id = get_router_model_id("balanced")
        expected_path = resolve_model_path(model_id)

        actual_path = classifier._resolve_model_path(model_id)
        assert actual_path == expected_path

    def test_router_tier_passed_to_classifier(self):
        """Test router passes tier to classifier."""
        router = IntentRouter(use_local=True, tier="performance")
        assert router.classifier._tier == "performance"

"""Tests for router module (pattern-based classification, ONNX removed in v0.8.0)."""

import pytest

from merlya.router.intent_classifier import (
    INTENT_PATTERNS,
    MODE_PATTERNS,
    TOOL_PATTERNS,
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
        assert AgentMode.DIAGNOSTIC in MODE_PATTERNS
        patterns = MODE_PATTERNS[AgentMode.DIAGNOSTIC]
        assert len(patterns) > 0

    def test_remediation_patterns_exist(self):
        """Test remediation patterns are defined."""
        assert AgentMode.REMEDIATION in MODE_PATTERNS
        patterns = MODE_PATTERNS[AgentMode.REMEDIATION]
        assert len(patterns) > 0

    def test_query_patterns_exist(self):
        """Test query patterns are defined."""
        assert AgentMode.QUERY in MODE_PATTERNS
        patterns = MODE_PATTERNS[AgentMode.QUERY]
        assert len(patterns) > 0

    def test_chat_patterns_exist(self):
        """Test chat patterns are defined."""
        assert AgentMode.CHAT in MODE_PATTERNS
        patterns = MODE_PATTERNS[AgentMode.CHAT]
        assert len(patterns) > 0

    def test_backward_compat_alias(self):
        """Test INTENT_PATTERNS is alias for MODE_PATTERNS."""
        assert INTENT_PATTERNS is MODE_PATTERNS


class TestToolPatterns:
    """Tests for tool pattern matching."""

    def test_system_patterns(self):
        """Test system tool patterns exist."""
        assert "system" in TOOL_PATTERNS
        assert len(TOOL_PATTERNS["system"]) > 0

    def test_files_patterns(self):
        """Test files tool patterns exist."""
        assert "files" in TOOL_PATTERNS
        assert len(TOOL_PATTERNS["files"]) > 0

    def test_security_patterns(self):
        """Test security tool patterns exist."""
        assert "security" in TOOL_PATTERNS
        assert len(TOOL_PATTERNS["security"]) > 0


class TestIntentClassifier:
    """Tests for IntentClassifier (pattern-based)."""

    def test_classifier_init(self):
        """Test classifier initialization."""
        classifier = IntentClassifier()
        assert not classifier.model_loaded  # ONNX removed
        assert classifier.embedding_dim is None

    def test_classify_diagnostic(self):
        """Test classification of diagnostic intent."""
        classifier = IntentClassifier()
        mode, conf = classifier.classify_patterns("check the status of nginx")
        assert mode == AgentMode.DIAGNOSTIC
        assert conf > 0.4

    def test_classify_remediation(self):
        """Test classification of remediation intent."""
        classifier = IntentClassifier()
        mode, conf = classifier.classify_patterns("restart the nginx service")
        assert mode == AgentMode.REMEDIATION
        assert conf > 0.4

    def test_classify_query(self):
        """Test classification of query intent."""
        classifier = IntentClassifier()
        mode, conf = classifier.classify_patterns("how do I configure nginx?")
        assert mode == AgentMode.QUERY
        assert conf > 0.4

    def test_classify_chat(self):
        """Test classification of chat intent."""
        classifier = IntentClassifier()
        mode, conf = classifier.classify_patterns("hello there")
        assert mode == AgentMode.CHAT
        assert conf > 0.4

    def test_classify_default(self):
        """Test default classification for unknown input."""
        classifier = IntentClassifier()
        mode, conf = classifier.classify_patterns("xyz123abc")
        assert mode == AgentMode.CHAT  # Default
        assert conf > 0

    def test_extract_entities_hosts(self):
        """Test entity extraction for hosts."""
        classifier = IntentClassifier()
        entities = classifier.extract_entities("connect to @webserver and @database")
        assert "hosts" in entities
        assert "webserver" in entities["hosts"]
        assert "database" in entities["hosts"]

    def test_extract_entities_services(self):
        """Test entity extraction for services."""
        classifier = IntentClassifier()
        entities = classifier.extract_entities("restart nginx and mysql")
        assert "services" in entities
        assert "nginx" in entities["services"]
        assert "mysql" in entities["services"]

    def test_determine_tools_system(self):
        """Test tool determination for system commands."""
        classifier = IntentClassifier()
        tools = classifier.determine_tools("check cpu usage", {})
        assert "core" in tools
        assert "system" in tools

    def test_determine_tools_docker(self):
        """Test tool determination for docker commands."""
        classifier = IntentClassifier()
        tools = classifier.determine_tools("list docker containers", {})
        assert "core" in tools
        assert "docker" in tools

    def test_determine_tools_with_hosts(self):
        """Test tool determination adds ssh for hosts."""
        classifier = IntentClassifier()
        tools = classifier.determine_tools("ls", {"hosts": ["server1"]})
        assert "core" in tools
        assert "ssh" in tools

    def test_check_delegation_ssh(self):
        """Test delegation detection for SSH."""
        classifier = IntentClassifier()
        delegate = classifier.check_delegation("ssh to the remote server")
        assert delegate == "ssh"

    def test_check_delegation_kubernetes(self):
        """Test delegation detection for Kubernetes."""
        classifier = IntentClassifier()
        delegate = classifier.check_delegation("get kubectl pods")
        assert delegate == "kubernetes"

    def test_check_delegation_none(self):
        """Test no delegation for generic commands."""
        classifier = IntentClassifier()
        delegate = classifier.check_delegation("check status")
        assert delegate is None


class TestIntentClassifierAsync:
    """Async tests for IntentClassifier."""

    @pytest.mark.asyncio
    async def test_load_model_returns_false(self):
        """Test load_model returns False (ONNX removed)."""
        classifier = IntentClassifier()
        result = await classifier.load_model()
        assert result is False

    @pytest.mark.asyncio
    async def test_classify_embeddings_fallback(self):
        """Test classify_embeddings falls back to patterns."""
        classifier = IntentClassifier()
        mode, conf = await classifier.classify_embeddings("check the server")
        assert mode == AgentMode.DIAGNOSTIC
        assert conf > 0.4

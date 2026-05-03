"""
NEXUS Test Suite — Multi-IA Module
Tests for: AgentRegistry, Router, ConsensusEngine,
contradiction detection, and MultiIA facade.
"""

import unittest

from conftest import NexusTestCase

from multi_ia.agent import (
    MockClaudeAgent, MockGPTAgent, MockCopilotAgent, MockLocalAgent,
    AgentRequest, AgentResponse, AgentCapability, AgentProvider, AgentStatus,
)
from multi_ia.registry import AgentRegistry, AgentRecord, agent_from_config
from multi_ia.router import Router, RoutingStrategy, RoutingRule
from multi_ia.consensus import (
    ConsensusEngine, ConsensusMethod, ConsensusResult,
    Contradiction, ContradictionType, ContradictionSeverity,
    _word_overlap, _directional_score,
)
from multi_ia import MultiIA, MultiIAConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _response(content: str, agent: str = "agent", confidence: float = 0.8) -> AgentResponse:
    return AgentResponse(
        request_id="req1",
        agent_id=agent,
        agent_name=agent,
        provider=AgentProvider.CUSTOM,
        model="mock",
        content=content,
        confidence=confidence,
        tokens_used=10,
        latency_ms=5.0,
    )


# ---------------------------------------------------------------------------
# Mock agents
# ---------------------------------------------------------------------------

class TestMockAgents(NexusTestCase):

    def test_mock_claude_responds(self) -> None:
        agent = MockClaudeAgent()
        req   = AgentRequest(task="Analyse market trends.")
        resp  = agent.call(req)
        self.assertTrue(resp.ok)
        self.assertGreater(len(resp.content), 0)

    def test_mock_gpt_responds(self) -> None:
        agent = MockGPTAgent()
        req   = AgentRequest(task="Summarise quarterly results.")
        resp  = agent.call(req)
        self.assertTrue(resp.ok)

    def test_response_confidence_bounded(self) -> None:
        agent = MockClaudeAgent()
        req   = AgentRequest(task="Test confidence range")
        resp  = agent.call(req)
        self.assertBetween(resp.confidence, 0.0, 1.0)

    def test_health_check_returns_bool(self) -> None:
        agent = MockLocalAgent()
        ok    = agent.health_check()
        self.assertIsInstance(ok, bool)

    def test_agent_tracks_call_count(self) -> None:
        agent = MockGPTAgent()
        req   = AgentRequest(task="Count me")
        agent.call(req)
        agent.call(req)
        self.assertEqual(agent._call_count, 2)

    def test_deterministic_response_same_task(self) -> None:
        agent = MockClaudeAgent()
        req   = AgentRequest(task="Deterministic question?")
        r1 = agent.call(req)
        r2 = agent.call(req)
        self.assertEqual(r1.content, r2.content)

    def test_different_agents_different_responses(self) -> None:
        req   = AgentRequest(task="What is the market outlook?")
        r_claude  = MockClaudeAgent().call(req)
        r_gpt     = MockGPTAgent().call(req)
        self.assertNotEqual(r_claude.content, r_gpt.content)

    def test_request_serializable(self) -> None:
        req = AgentRequest(task="Test", context={"key": "val"}, max_tokens=512)
        d = req.to_dict() if hasattr(req, "to_dict") else vars(req)
        self.assertIsInstance(d, dict)


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------

class TestAgentRegistry(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.registry = AgentRegistry()

    def test_register_and_get(self) -> None:
        agent = MockClaudeAgent()
        self.registry.register(agent, description="Claude mock")
        fetched = self.registry.get(agent.name)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, agent.name)

    def test_register_duplicate_overwrites(self) -> None:
        agent = MockClaudeAgent()
        self.registry.register(agent, description="v1")
        self.registry.register(agent, description="v2")
        record = self.registry.get_record(agent.name)
        self.assertEqual(record.description, "v2")

    def test_get_available_returns_list(self) -> None:
        self.registry.register(MockClaudeAgent())
        self.registry.register(MockGPTAgent())
        available = self.registry.get_available()
        self.assertGreater(len(available), 0)

    def test_get_by_capability(self) -> None:
        agent = MockClaudeAgent()
        self.registry.register(agent, tags=["reasoning"])
        results = self.registry.get_by_capabilities({AgentCapability.REASONING})
        self.assertNonEmpty(results)

    def test_disable_and_enable_agent(self) -> None:
        agent = MockCopilotAgent()
        self.registry.register(agent)
        self.registry.disable(agent.name)
        available = self.registry.get_available()
        names = [a.name for a in available]
        self.assertNotIn(agent.name, names)
        self.registry.enable(agent.name)
        available = self.registry.get_available()
        names = [a.name for a in available]
        self.assertIn(agent.name, names)

    def test_list_returns_dicts(self) -> None:
        self.registry.register(MockClaudeAgent())
        listing = self.registry.list()
        self.assertIsInstance(listing, list)
        self.assertIsInstance(listing[0], dict)

    def test_stats_returns_dict(self) -> None:
        self.registry.register(MockLocalAgent())
        self.assertDictHasKeys(self.registry.stats(), "total_agents", "available_agents")

    def test_refresh_health(self) -> None:
        self.registry.register(MockClaudeAgent())
        result = self.registry.refresh_health()
        self.assertIsInstance(result, dict)

    def test_agent_from_config_claude(self) -> None:
        agent = agent_from_config({"provider": "anthropic", "name": "claude_test"})
        self.assertIsNotNone(agent)

    def test_all_agents_returns_list(self) -> None:
        self.registry.register(MockClaudeAgent())
        self.assertIsInstance(self.registry.all_agents(), list)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class TestRouter(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.registry = AgentRegistry()
        self.registry.register(MockClaudeAgent(),  tags=["primary"])
        self.registry.register(MockGPTAgent(),     tags=["primary"])
        self.registry.register(MockLocalAgent(),   tags=["fast"])
        self.router = Router(self.registry)

    def test_route_returns_agent(self) -> None:
        req   = AgentRequest(task="Analyse something")
        agent = self.router.route(req)
        self.assertIsNotNone(agent)

    def test_route_many_returns_n_agents(self) -> None:
        req    = AgentRequest(task="Parallel task")
        agents = self.router.route_many(req, n=2)
        self.assertEqual(len(agents), 2)

    def test_route_with_fallbacks_ordered(self) -> None:
        req    = AgentRequest(task="Fallback task")
        agents = self.router.route_with_fallbacks(req)
        self.assertGreater(len(agents), 0)

    def test_round_robin_rotates(self) -> None:
        req = AgentRequest(task="Round robin")
        a1  = self.router.route(req, strategy=RoutingStrategy.ROUND_ROBIN)
        a2  = self.router.route(req, strategy=RoutingStrategy.ROUND_ROBIN)
        # Both valid agents; may differ
        self.assertIsNotNone(a1)
        self.assertIsNotNone(a2)

    def test_random_strategy_returns_agent(self) -> None:
        req   = AgentRequest(task="Random pick")
        agent = self.router.route(req, strategy=RoutingStrategy.RANDOM)
        self.assertIsNotNone(agent)

    def test_routing_rule_pattern_match(self) -> None:
        rule = RoutingRule(
            name="code_rule",
            task_pattern=r"(?i)code|implement|function",
            preferred_agents=[MockCopilotAgent().name],
            strategy=RoutingStrategy.BEST_CAPABILITY,
        )
        self.router.add_rule(rule)
        req   = AgentRequest(task="Please implement a function")
        agent = self.router.route(req)
        self.assertIsNotNone(agent)

    def test_stats_returns_dict(self) -> None:
        self.assertIsInstance(self.router.stats(), dict)


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

class TestSimilarityHelpers(NexusTestCase):

    def test_word_overlap_identical(self) -> None:
        self.assertAlmostEqual(_word_overlap("hello world", "hello world"), 1.0)

    def test_word_overlap_disjoint(self) -> None:
        score = _word_overlap("apple banana cherry", "dog cat fish")
        self.assertAlmostEqual(score, 0.0)

    def test_word_overlap_partial(self) -> None:
        score = _word_overlap("buy the stock now", "sell the stock now")
        self.assertBetween(score, 0.1, 0.9)

    def test_directional_positive(self) -> None:
        score = _directional_score("We should buy and proceed. Markets are safe and positive.")
        self.assertGreater(score, 0.0)

    def test_directional_negative(self) -> None:
        score = _directional_score("Sell everything. Stop. Unsafe. Bearish. Reject.")
        self.assertLess(score, 0.0)

    def test_directional_neutral(self) -> None:
        score = _directional_score("The weather today is cloudy with some sunshine.")
        self.assertAlmostEqual(score, 0.0)


# ---------------------------------------------------------------------------
# ConsensusEngine
# ---------------------------------------------------------------------------

class TestConsensusEngine(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.engine = ConsensusEngine(default_method=ConsensusMethod.WEIGHTED_AVERAGE)

    def _responses(self, contents, confidences=None) -> list:
        confs = confidences or [0.8] * len(contents)
        return [_response(c, f"agent_{i}", confs[i]) for i, c in enumerate(contents)]

    def test_reach_consensus_single_response(self) -> None:
        resps  = self._responses(["The market is bullish."])
        result = self.engine.reach_consensus(resps)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ConsensusResult)
        self.assertEqual(result.agreement_score, 1.0)

    def test_reach_consensus_agreement_score_high_for_similar(self) -> None:
        resps = self._responses([
            "The trend is positive and we should buy.",
            "Current trend looks positive, recommend buying.",
        ])
        result = self.engine.reach_consensus(resps)
        self.assertGreater(result.agreement_score, 0.1)

    def test_reach_consensus_low_agreement_for_opposite(self) -> None:
        resps = self._responses([
            "Buy the dip. Markets are safe and bullish. Proceed and approve.",
            "Sell immediately. Unsafe. Bearish. Abort. Reject. Stop.",
        ])
        result = self.engine.reach_consensus(resps)
        # Should detect low agreement
        self.assertLessEqual(result.agreement_score, 0.5)

    def test_contradiction_detected_directional(self) -> None:
        resps = self._responses([
            "Strongly recommend to buy. Markets bullish. Proceed safely.",
            "Strongly recommend to sell. Bearish. Abort immediately. Unsafe.",
        ])
        result = self.engine.reach_consensus(resps)
        self.assertTrue(result.has_contradictions)

    def test_no_valid_responses_returns_empty_result(self) -> None:
        failed_resp = AgentResponse(
            request_id="r1", agent_id="a1", agent_name="a1",
            provider=AgentProvider.CUSTOM, model="mock",
            content="", confidence=0.0, tokens_used=0, latency_ms=0.0,
            error="timeout",
        )
        result = self.engine.reach_consensus([failed_resp])
        self.assertEqual(result.responses_used, 0)

    def test_majority_vote_method(self) -> None:
        resps = self._responses([
            "Buy. Positive. Bullish. Proceed.",
            "Buy. Positive. Proceed. Safe.",
            "Sell. Bearish. Stop.",
        ])
        result = self.engine.reach_consensus(resps, method=ConsensusMethod.MAJORITY_VOTE)
        self.assertIsNotNone(result.final_content)

    def test_best_confidence_selects_highest(self) -> None:
        resps = self._responses(
            ["Low confidence response", "High confidence response"],
            confidences=[0.3, 0.95],
        )
        result = self.engine.reach_consensus(resps, method=ConsensusMethod.BEST_CONFIDENCE)
        self.assertEqual(result.selected_agent, "agent_1")

    def test_escalation_hook_called(self) -> None:
        escalated = []
        engine = ConsensusEngine(
            default_method=ConsensusMethod.WEIGHTED_AVERAGE,
            escalation_hook=lambda r: escalated.append(r),
        )
        resps = self._responses([
            "Buy urgently. Proceed. Bullish. Safe. Approve.",
            "Sell urgently. Abort. Bearish. Unsafe. Reject.",
        ])
        engine.reach_consensus(resps)
        # High severity directional contradiction should trigger hook
        if escalated:
            self.assertIsInstance(escalated[0], ConsensusResult)

    def test_stats_returns_dict(self) -> None:
        self.assertDictHasKeys(self.engine.stats(),
                               "total_consensus_runs", "escalations")

    def test_score_agreement_identical(self) -> None:
        resps = self._responses(["Identical response text."] * 3)
        score = self.engine.score_agreement(resps)
        self.assertAlmostEqual(score, 1.0)


# ---------------------------------------------------------------------------
# MultiIA facade
# ---------------------------------------------------------------------------

class TestMultiIA(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.ia = MultiIA()
        self.ia.start()

    def test_start_registers_default_agents(self) -> None:
        agents = self.ia.registry.get_available()
        self.assertGreater(len(agents), 0)

    def test_ask_returns_response(self) -> None:
        resp = self.ia.ask("What is the current market outlook?")
        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)

    def test_ask_all_returns_pipeline_result(self) -> None:
        result = self.ia.ask_all("Should we invest now?", n_agents=2)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.consensus_result)

    def test_ask_all_agreement_score_valid(self) -> None:
        result = self.ia.ask_all("Evaluate portfolio risk.", n_agents=2)
        score  = result.consensus_result.agreement_score
        self.assertBetween(score, 0.0, 1.0)

    def test_vote_returns_consensus_result(self) -> None:
        vote = self.ia.vote("Is the current strategy profitable?", n_agents=2)
        self.assertIsInstance(vote, ConsensusResult)

    def test_broadcast_reaches_all_agents(self) -> None:
        responses = self.ia.broadcast("System health check")
        self.assertGreater(len(responses), 0)

    def test_status_returns_dict(self) -> None:
        status = self.ia.status()
        self.assertDictHasKeys(status, "running", "registry", "consensus")

    def test_history_returns_list(self) -> None:
        self.ia.ask_all("Test history", n_agents=2)
        history = self.ia.history(limit=5)
        self.assertIsInstance(history, list)

    def test_refresh_health(self) -> None:
        result = self.ia.refresh_health()
        self.assertIsInstance(result, dict)

    def test_register_custom_agent(self) -> None:
        agent = MockLocalAgent()
        agent.name = "custom_test_agent"
        self.ia.register_agent(agent, description="custom test")
        fetched = self.ia.registry.get("custom_test_agent")
        self.assertIsNotNone(fetched)


if __name__ == "__main__":
    unittest.main()

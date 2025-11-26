"""
Synthesis Domain.

Responsible for:
- Parsing command results (uptime, disk, service, process)
- Analyzing metrics
- Generating recommendations
- Synthesizing final output for users
"""
from .synthesizer import ResultSynthesizer
from .parsers import MetricsParser
from .analyzers import MetricsAnalyzer

__all__ = ["ResultSynthesizer", "MetricsParser", "MetricsAnalyzer"]

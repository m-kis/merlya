"""
Synthesis Domain.

Responsible for:
- Parsing command results (uptime, disk, service, process)
- Analyzing metrics
- Generating recommendations
- Synthesizing final output for users
"""
from .analyzers import MetricsAnalyzer
from .parsers import MetricsParser
from .synthesizer import ResultSynthesizer

__all__ = ["ResultSynthesizer", "MetricsParser", "MetricsAnalyzer"]

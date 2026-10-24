"""The desk: fan out, then reconcile."""
from google.adk.agents import ParallelAgent, SequentialAgent

import reconciler
from specialists import all_specialists


def build_desk() -> SequentialAgent:
    evidence = ParallelAgent(name="evidence", sub_agents=all_specialists())
    return SequentialAgent(
        name="underwriting_desk",
        sub_agents=[evidence, reconciler.build()],
    )


def build_sequential_desk() -> SequentialAgent:
    """The same four reads, one after another. For the timing comparison."""
    return SequentialAgent(
        name="underwriting_desk_sequential",
        sub_agents=[*all_specialists(), reconciler.build()],
    )

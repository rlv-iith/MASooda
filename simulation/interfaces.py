"""Public function shapes shared by the project modules.

- This file tells each module what inputs and outputs to expect.  
- It acts like an agreement between team members: P4 can improve the overseer internally,
while P1 and P3 continue calling the same function.
"""

from __future__ import annotations
from typing import Protocol
from .schema import GlobalStateSnapshot, OverseerDirective
from .overseer import mock_overseer_update


class OverseerUpdate(Protocol):
    """Describe the input and output shape of any overseer implementation.

    ``Protocol`` is a typing tool. It lets static checkers confirm that a
    function has the right shape without forcing every implementation to
    inherit from this class. It does not run the overseer itself.
    """

    def __call__(self, global_state_snapshot: GlobalStateSnapshot) -> OverseerDirective:
        """Create one global directive from the current state summary."""


def overseer_update(global_state_snapshot: GlobalStateSnapshot) -> OverseerDirective:
    """Provide the project's single entry point for an overseer update.

    - P1 or P3 can call this function without knowing where the implementation lives.  
    - In Week 1 it returns the fixed mock directive.  
    - In Week 2 P4 will replace the mock with occupancy-based corridor allocation.  
    - In Week 3 P4 will add priority-aware allocation and capacity handling.  
    - In Week 4 P4 will support cached directives when the overseer link fails.
    """
    

    return mock_overseer_update(global_state_snapshot)

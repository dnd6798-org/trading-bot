"""
Pipeline step 5 (spec §3.1.5): position management.

Monitors open positions until closed. Given the crypto bracket-order gap
(see execution.py), this loop is a more load-bearing safety layer than
originally assumed for stocks — it must detect when one exit leg (stop or
take-profit) fills and cancel the other (software-emulated OCO), not just
watch for its own independent exit conditions.
"""


def monitor_open_positions(open_positions):
    raise NotImplementedError("Build session — depends on execution.py design fix")


def cancel_counterpart_order(filled_order_id: str, stop_order_id: str, take_profit_order_id: str):
    """Software-emulated OCO: cancel whichever leg didn't fill."""
    raise NotImplementedError

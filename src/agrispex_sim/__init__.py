"""AgriSPEX synthetic IoT simulator.

The FARM5.0 field sensors are decommissioned, so no further real IoT data will
arrive. This package provides a calibrated synthetic IoT generator for two
clearly-labelled, legitimate research/operational uses:

1. Dataset completion - fill an IoT context vector for EO windows that have no
   real sensor match, so every training patch has an aligned vector. Every
   synthetic value is flagged ``iot_source = "synthetic"``; real values are kept
   as-is and flagged ``"real"``.

2. Operational stand-in - generate IoT context vectors on demand (per timestamp
   or as a continuous stream) for when the service runs on Testbed-3 without live
   sensors.

IMPORTANT: synthetic data is for model training/augmentation and operational
simulation only. It does NOT change the measured OP-8 real IoT-fusion uptime
(58.6% on the historical dataset); that remains a live-Testbed measurement.
"""

from .iot_simulator import IoTSimulator  # noqa: F401

__version__ = "1.0.0"

"""Free-to-promise computation and Safe/AtRisk/AtRiskSevere/Blocked classification.

Per D-010 + formalism §5. The FTP formula partitions inventory by temperature
band; the classifier applies the fill-rate tripwire pattern.
"""

from verdano.allocation.classify import Classifier
from verdano.allocation.ftp import FTPCalculator

__all__ = ["Classifier", "FTPCalculator"]

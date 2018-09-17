"""
Represents covariates in the model.
"""
import logging
from cascade.model.rates import Smooth


CODELOG = logging.getLogger(__name__)
MATHLOG = logging.getLogger(__name__)


class CovariateColumn:
    """
    Establishes a reference value for a covariate column on input data
    and in output data. It is possible to create a covariate column with
    nothing but a name, but it must have a reference value before it
    can be used in a model.

    Args:
        column_name (str): Name of hte column in the input data.
        reference (float): Optional reference where covariate has no effect.
        max_difference (float, optional):
            If a data point's covariate is farther than `max_difference`
            from the reference value, then this data point is excluded
            from the calculation.
    """
    def __init__(self, column_name, reference=None, max_difference=None):
        self._name = None
        self._reference = None
        self._max_difference = None

        self.name = column_name
        if reference is not None:
            self.reference = reference
        self.max_difference = max_difference

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, nom):
        if not isinstance(nom, str):
            raise ValueError(f"CovariateColumn name must be a string {nom}")
        if len(nom) < 1:
            raise ValueError(f"CovariateColumn name must not be empty string")
        self._name = nom

    @property
    def reference(self):
        return self._reference

    @reference.setter
    def reference(self, ref):
        self._reference = float(ref)

    @property
    def max_difference(self):
        return self._max_difference

    @max_difference.setter
    def max_difference(self, difference):
        if difference is None:
            self._max_difference = None
        else:
            diff = float(difference)
            if diff <= 0:
                raise ValueError(f"max difference must be positive {difference}")
            self._max_difference = diff

    def __repr__(self):
        return f"CovariateColumn({self.name}, {self.reference}, {self.max_difference})"

    def __eq__(self, other):
        return (self._name == other.name and self._reference == other._reference
                and self._max_difference == other._max_difference)


class CovariateMultiplier:
    """
    A covariate multiplier makes a given covariate column the predictor
    of a model variable, where the model variable can be one of a
    rate, an integrand's value, or an integrand's standard deviation.

    This class is only two-thirds of the definition.
    The covariate column has to be attached to a particular rate
    or measured value or measured standard deviation.
    """
    def __init__(self, covariate_column, smooth):
        """
        Args:
            covariate_column (CovariateColumn): Which predictor to use.
            smooth (Smooth): Each covariate gets a smoothing grid.
        """
        if not isinstance(covariate_column, CovariateColumn):
            raise ValueError("Second argument must be a Smooth.")
        if not isinstance(smooth, Smooth):
            raise ValueError("Second argument must be a Smooth.")

        self.column = covariate_column
        self.smooth = smooth

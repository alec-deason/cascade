from math import nan
from pathlib import Path

import pandas as pd

from cascade.core import getLoggers
from cascade.core.subprocess_utils import run_with_logging
from cascade.dismod.constants import COMMAND_IO
from cascade.dismod import DismodATException
from cascade.model import Model
from cascade.model.object_wrapper import ObjectWrapper

CODELOG, MATHLOG = getLoggers(__name__)


class Session:
    """
    A Session interacts with Dismod-AT. It estimates fits,
    predicts rates, and simulates. Collaborates with the ObjectWrapper
    to manipulate the DismodFile.
    """
    def __init__(self, locations, parent_location, filename):
        """
        A session represents a connection with a Dismod-AT backend through
        a single Dismod-AT db file, the sqlite file it uses for input and
        output.

        Args:
            locations (pd.DataFrame): Both the model and data refer to a
                hierarchy of locations. Supply those as a DataFrame
                with ``location_id`` as an integer, ``parent_id`` as an integer,
                and an optional ``name`` as a string.
            parent_location (int): The session uses parent location to subset
                data, but it isn't in the model. This is a location ID supplied
                in the locations argument.
            filename (str|Path): Location of the Dismod db to overwrite.
        """
        assert isinstance(locations, pd.DataFrame)
        assert isinstance(parent_location, int)
        assert isinstance(filename, (Path, str))

        self._filename = filename
        self._objects = ObjectWrapper(locations, parent_location, filename)
        self._options = dict()

    def fit(self, model, data, initial_guess=None):
        """This is a fit without a predict. If the model
        has random effects, this optimizes over both fixed
        and random effects.

        Args:
            model (Model): A model, possibly without scale vars.
            data (pd.DataFrame): Data to fit.
            initial_guess (Var): Starting point to look for solutions. If not
                given, then the mean of the priors is taken as the initial
                guess.

        Returns:
            DismodGroups[Var]: A set of fit var.
        """
        if model.random_effect:
            MATHLOG.info(f"Running fit both.")
            return self._fit("both", model, data, initial_guess)
        else:
            MATHLOG.info(f"Running fit fixed.")
            return self._fit("fixed", model, data, initial_guess)

    def fit_fixed(self, model, data, initial_guess=None):
        """Fits a model without optimizing over any random effects.
        It does apply constant child value priors, but other random effects
        are constrained to zero. (This is equivalent to fitting with
        ``bound_random`` equal to zero.) This is useful when one uses fitting
        with no random effects as a starting point for fitting with
        random effects.

        Args:
            model (Model): A model, possibly without scale vars.
            data (pd.DataFrame): Data to fit.
            initial_guess (Var): Starting point to look for solutions. If not
                given, then the mean of the priors is taken as the initial
                guess.

        Returns:
            DismodGroups[Var]: A set of fit var.
        """
        return self._fit("fixed", model, data, initial_guess)

    def fit_random(self, model, data, initial_guess=None):
        """
        Fits the data with the model.
        This optimizes the random effects with the fixed effects set to their
        starting values. The fixed effects are unchanged.

        Args:
            model (Model): A model, possibly without scale vars.
            data (pd.DataFrame): Data to fit.
            initial_guess (Var): Starting point to look for solutions. If not
                given, then the mean of the priors is taken as the initial
                guess.

        Returns:
            DismodGroups[Var]: A set of fit var.
        """
        return self._fit("random", model, data, initial_guess)

    def _fit(self, fit_level, model, data, initial_guess):
        if initial_guess:
            misalignment = model.check_alignment(initial_guess)
            if misalignment:
                raise RuntimeError(f"Model and initial guess are misaligned: {misalignment}.")
        data = Session._amend_data_input(data)
        self.setup_model_for_fit(model, data, initial_guess)
        if initial_guess is not None:
            MATHLOG.info(f"Setting initial value for search from user argument.")
            self._objects.start_var = initial_guess
        # else use the one generated by the call to init, coming from the mean.
        dm_out, dm_err = self._run_dismod(["fit", fit_level])
        return FitResult(self._objects, self._objects.fit_var, dm_out, dm_err)

    def setup_model_for_fit(self, model, data=None, initial_guess=None):
        """Writes a model and options to a db file and runs init on it.
        This isn't normally run in the course of work but can be helpful
        if you want to tweak the db file before running a fit.

        Args:
            model (Model): The model object.
            data (pd.DataFrame|None): Can be None.
            initial_guess (Var|None): Initial values, can be None.
        """
        data = Session._point_age_time_to_interval(data)
        self._objects.model = model
        self._objects.set_option(**self._options)
        self._objects.data = data
        self._run_dismod(["init"])
        if model.scale_set_by_user:
            self._objects.scale_var = model.scale
        elif initial_guess is not None:
            self._objects.scale_var = initial_guess
        else:
            # Assign to the private variable because setting the property
            # indicates that the user of the API wants to set their own scale
            # instead of using the one Dismod-AT calculates during init.
            model._scale = self._objects.scale_var

    def predict(self, var, avgint, parent_location, weights=None, covariates=None):
        """Given rates, calculated the requested average integrands.

        Args:
            var (DismodGroups): Var objects with rates.
            avgint (pd.DataFrame): Request data in these ages, times, and
                locations. Columns are ``integrand`` (str), ``location``
                (location_id), ``age_lower`` (float), ``age_upper`` (float),
                ``time_lower`` (float), ``time_upper`` (float). The integrand
                should be one of the names in IntegrandEnum.
            parent_location: The id of the parent location.
            weights (Dict[Var]): Weights are estimates of ``susceptible``,
                ``with_condition``, and ``total`` populations, used to bias
                integrands with age or time extent. Each one is a single
                Var object.
            covariates (List[Covariate]): A list of Covariates, so that we know
                the name and reference value for each.

        Returns:
            (pd.DataFrame, pd.DataFrame): The predicted avgints, and a dataframe
            of those not predicted because their covariates are greater than
            ``max_difference`` from the ``reference`` covariate value.
            Columns in the ``predicted`` are ``sample_index``,
            ``mean`` (this is the value), ``location``, ``integrand``,
            ``age_lower``, ``age_upper``, ``time_lower``, ``time_upper``.
        """
        self._check_vars(var)
        model = Model.from_var(var, parent_location, weights=weights, covariates=covariates)
        avgint = Session._point_age_time_to_interval(avgint)
        self._objects.model = model
        self._objects.set_option(**self._options)
        self._objects.avgint = avgint

        self._run_dismod(["init"])
        self._objects.truth_var = var
        self._run_dismod(["predict", "truth_var"])
        predicted, not_predicted = self._objects.predict
        return predicted, not_predicted

    def simulate(self, model, data, fit_var, simulate_count):
        """Simulates posterior distribution for model variables.

        This is described in several places:
        https://bradbell.github.io/dismod_at/doc/posterior.htm
        https://bradbell.github.io/dismod_at/doc/simulate_command.htm
        https://bradbell.github.io/dismod_at/doc/user_posterior.py.htm

        Args:
            model (Model): A model. The mean of the prior is ignored.
            data (DataFrame): Same format as for a fit.
            fit_var (Var): A set of model variables around which to simulate.
            simulate_count (int): Number of simulations to generate.

        Returns:
            (DataFrame, Groups of SmoothGrids): These are the data simulations
            and the prior simulations. The former are stacked in a dataframe
            with an index, and the latter are in a DismodGroups container
            of SmoothGrids.
        """
        # Ensure data has name, nu, eta, time_upper and lower.
        data = Session._amend_data_input(data)
        if fit_var:
            misalignment = model.check_alignment(fit_var)
            if misalignment:
                raise RuntimeError(f"Model and fit var are misaligned: {misalignment}.")
        self.setup_model_for_fit(model, data, fit_var)
        self._objects.truth_var = fit_var
        self._run_dismod(["simulate", simulate_count])
        return SimulateResult(self._objects, simulate_count, model, data)

    def sample(self, simulate_result):
        """Given that a simulate has been run, make samples.

        Args:
            simulate_result (SimulateResult): Output of a simulate command.

        Returns:
            DismodGroups[Var] with multiple samples.
        """
        self._run_dismod(["sample", "simulate", simulate_result.count])
        return self._objects.samples

    def set_option(self, **kwargs):
        self._options.update(kwargs)
        if self._objects.dismod_file:
            self._objects.set_option(**self._options)

    def set_minimum_meas_cv(self, **kwargs):
        """Sets the minimum coefficient of variation for this integrand.
        The name is one of :py:class:`cascade.dismod.constants.IntegrandEnum`.
        integrand_name (str) The canonical Dismod-AT name for the integrand.
        value (float) A value greater-than or equal to zero. If it is
        zero, then there is no coefficient of variation for this integrand.

        Args:
            name-value pairs: This is a set of integrand=value pars.
        """
        for integrand_name, value in kwargs.items():
            self._objects.set_minimum_meas_cv(integrand_name, value)

    def _run_dismod(self, command):
        """Pushes tables to the db file, runs Dismod-AT, and refreshes
        tables written."""
        self._objects.flush()
        CODELOG.debug(f"Running Dismod-AT {command}")
        with self._objects.close_db_while_running():
            str_command = [str(c) for c in command]
            return_code, stdout, stderr = run_with_logging(
                ["dmdismod", str(self._filename)] + str_command)

        self._check_dismod_command(str_command[0], stdout, stderr)
        assert return_code == 0, f"return code is {return_code}"
        if command[0] in COMMAND_IO:
            self._objects.refresh(COMMAND_IO[command[0]].output)
        return stdout, stderr

    def _check_dismod_command(self, command, stdout, stderr):
        log = self._objects.log
        oom_sentinel = "std:bad_alloc"
        max_iter_sentinel = "Maximum Number of Iterations Exceeded"
        if len(log) == 0 or f"end {command}" not in log.message.iloc[-1]:
            if oom_sentinel in stdout or oom_sentinel in stderr:
                raise DismodATException("Dismod-AT ran out of memory")
            elif max_iter_sentinel in stdout or max_iter_sentinel in stderr:
                MATHLOG.warning("Dismod-AT exceeded iterations")
            else:
                raise DismodATException(f"Dismod-AT failed to complete '{command}' command")

    @staticmethod
    def _check_vars(var):
        for group_name, group in var.items():
            for key, one_var in group.items():
                one_var.check(f"{group_name}-{key}")

    @staticmethod
    def _point_age_time_to_interval(data):
        if data is None:
            return
        for at in ["age", "time"]:  # Convert from point ages and times.
            for lu in ["lower", "upper"]:
                if f"{at}_{lu}" not in data.columns and at in data.columns:
                    data = data.assign(**{f"{at}_{lu}": data[at]})
        return data.drop(columns={"age", "time"} & set(data.columns))

    @staticmethod
    def _amend_data_input(data):
        """If the data comes in without optional entries, add them.
        This doesn't translate to internal IDs for Dismod-AT. It rectifies
        the input, and this is how it should be saved or passed to another tool.
        """
        data = Session._point_age_time_to_interval(data)

        if "name" not in data.columns:
            data = data.assign(name=data.index.astype(str))
        else:
            null_names = data[data.name.isnull()]
            if not null_names.empty:
                raise RuntimeError(f"There are some data values that lack data names. {null_names}")

        if "hold_out" not in data.columns:
            data = data.assign(hold_out=0)
        for additional in ["nu", "eta"]:
            if additional not in data.columns:
                data = data.assign(**{additional: nan})
        return data


class FitResult:
    """Outcome of a Dismod-AT fit"""
    def __init__(self, file_objects, fit_var, dm_out, dm_err):
        self._file_objects = file_objects
        self._fit_var = fit_var
        self.dismod_out = dm_out
        self.dismod_err = dm_err

    @property
    def success(self):
        return "Optimal Solution Found" in self.dismod_out

    @property
    def fit(self):
        """All model variables. This is a DismodGroups instance."""
        return self._fit_var

    @property
    def prior_residuals(self):
        """The difference between model variables and their prior means.
        Prior residuals in a DismodGroups instance."""
        return self._file_objects.prior_residuals

    @property
    def data_residuals(self):
        """The difference between input data and output estimates of data.
        A DataFrame of residuals, identified by name from input data."""
        return self._file_objects.data_residuals

    @property
    def fit_data(self):
        """Which of the data points were fit."""
        raise NotImplementedError(f"Cannot retrieve fit data subset.")

    @property
    def excluded_data(self):
        """Which of the data points were excluded due
        to hold outs or covariates."""
        raise NotImplementedError(f"Cannot retrieve excluded data points.")


class SimulateResult:
    """Outcome of a Dismod-AT Simulate."""
    def __init__(self, file_objects, count, model, data):
        self._file_objects = file_objects
        self._count = count
        self._model = model
        self._data = data

    @property
    def count(self):
        return self._count

    def simulation(self, index):
        """Retrieve one of the simulations as a model and data.

        Args:
            index (int): Which simulation to retrieve, zero-based.

        Returns:
            Model, Data: A new model and data, modified to be
            the Nth simulation.
        """
        return self._file_objects.read_simulation_model_and_data(self._model, self._data, index)

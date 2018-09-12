"""A representation of the configuration form we expect to receive from EpiViz.
The hope is that this form will do as much validation and precondition checking
as is feasible within the constraint that it must be able to validate a full
EpiViz parameter document in significantly less than one second. This is
because it will be used as part of a web service which gates EpiViz submissions
and must return in near real time.

The Configuration class is the root of the form.

"""
from cascade.core.form import Form, IntField, FloatField, StrField, StringListField, OptionField, FormList, Dummy
from cascade.model import priors


class SmoothingPrior(Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prior_object = None

    prior_type = OptionField(["dage", "dtime", "value"])
    age_lower = FloatField(nullable=True)
    age_upper = FloatField(nullable=True)
    time_lower = FloatField(nullable=True)
    time_upper = FloatField(nullable=True)
    density = OptionField(["uniform", "gaussian", "laplace", "students", "log_gaussian", "log_laplace", "log_students"])
    min = FloatField(nullable=True, default=float("-inf"))
    mean = FloatField(nullable=True)
    max = FloatField(nullable=True, default=float("inf"))
    std = FloatField(nullable=True)
    nu = FloatField(nullable=True)
    eta = FloatField(nullable=True)

    def _full_form_validation(self):
        errors = []

        if not self.is_field_unset("age_lower") and not self.is_field_unset("age_lower"):
            if self.age_lower > self.age_upper:
                errors.append("age_lower must be less than or equal to age_upper")
        if not self.is_field_unset("time_lower") and not self.is_field_unset("time_lower"):
            if self.time_lower > self.time_upper:
                errors.append("time_lower must be less than or equal to time_upper")

        try:
            if self.density == "uniform":
                self.prior_object = priors.Uniform(self.min, self.max, self.mean)
            elif self.density == "gaussian":
                self.prior_object = priors.Gaussian(self.mean, self.std, self.min, self.max)
            elif self.density == "laplace":
                self.prior_object = priors.Laplace(self.mean, self.std, self.min, self.max)
            elif self.density == "students":
                self.prior_object = priors.StudentsT(self.mean, self.std, self.nu, self.min, self.max, self.eta)
            elif self.density == "log_gaussian":
                self.prior_object = priors.LogGaussian(self.mean, self.std, self.eta, self.min, self.max)
            elif self.density == "log_laplace":
                self.prior_object = priors.LogLaplace(self.mean, self.std, self.eta, self.min, self.max)
            elif self.density == "log_students":
                self.prior_object = priors.LogStudentsT(self.mean, self.std, self.nu, self.eta, self.min, self.max)
            else:
                errors.append(f"Unknown density '{self.density}'")
        except priors.PriorError as e:
            errors.append(f"Parameters incompatible with density '{self.density}': {str(e)}")

        return errors


class SmoothingPriorGroup(Form):
    dage = SmoothingPrior(name_field="prior_type")
    dtime = SmoothingPrior(name_field="prior_type")
    value = SmoothingPrior(name_field="prior_type")


class Smoothing(Form):
    rate = IntField()
    age_grid = StringListField(constructor=float, nullable=True)
    time_grid = StringListField(constructor=float, nullable=True)
    default = SmoothingPriorGroup()
    mulstd = SmoothingPriorGroup(nullable=True)
    detail = FormList(SmoothingPrior, nullable=True)

    custom_age_grid = Dummy()
    custom_time_grid = Dummy()


class Model(Form):
    modelable_entity_id = IntField()
    title = StrField()
    description = StrField()
    bundle_id = IntField(nullable=True)
    drill = OptionField(["cascade", "drill"])
    drill_location = IntField()
    drill_sex = OptionField([1, 2], nullable=True)
    default_age_grid = StringListField(constructor=float)
    default_time_grid = StringListField(constructor=float)


class Configuration(Form):
    """ The root Form of the whole configuration tree.

    Example:
        >>> input_data = json.loads(json_blob)
        >>> form = Configuration(input_data)
        >>> errors = form.validate_and_normalize()
        >>> if errors:
                print(errors)
                raise Exception("Woops")
            else:
                print(f"Ready to configure a model for {form.model.modelable_entity_id}")

    """

    model = Model()
    gbd_round_id = IntField()
    random_effect = FormList(Smoothing, nullable=True)
    rate = FormList(Smoothing)

    csmr_cod_output_version_id = Dummy()
    csmr_mortality_output_version_id = Dummy()
    location_set_version_id = Dummy()
    min_cv = FormList(Dummy)
    min_cv_by_rate = FormList(Dummy)
    re_bound_location = FormList(Dummy)
    study_covariate = Dummy()
    country_covariate = Dummy()
    derivative_test = Dummy()
    max_num_iter = Dummy()
    print_level = Dummy()
    accept_after_max_steps = Dummy()
    tolerance = Dummy()
    students_dof = Dummy()
    log_students_dof = Dummy()
    eta = Dummy()
    data_eta_by_integrand = Dummy()
    data_density_by_integrand = Dummy()
    config_version = Dummy()

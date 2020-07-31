'''This sets up and runs a simple system which is low-dimensional enough to
do locally'''
from numpy import array
from time import time as get_time
from scipy.integrate import solve_ivp
from model.preprocessing import (
    TwoAgeModelInput, HouseholdPopulation, make_initial_condition)
from model.specs import DEFAULT_SPEC
from model.common import RateEquations
# pylint: disable=invalid-name

model_input = TwoAgeModelInput(DEFAULT_SPEC)

# List of observed household compositions
composition_list = array(
    [[0, 1], [0, 2], [1, 1], [1, 2], [2, 1], [2, 2]])
# Proportion of households which are in each composition
comp_dist = array([0.2, 0.2, 0.1, 0.1, 0.1,  0.1])

household_population = HouseholdPopulation(
    composition_list, comp_dist, model_input)

rhs = RateEquations(
    model_input,
    household_population)

H0 = make_initial_condition(
    household_population, rhs)

tspan = (0.0, 1000)
simple_model_start = get_time()
solution = solve_ivp(rhs, tspan, H0, first_step=0.001)
simple_model_end = get_time()

time = solution.t
H = solution.y
D = H.T.dot(household_population.states[:, 2::5])
U = H.T.dot(household_population.states[:, 3::5])

print(
    'Simple model took ',
    simple_model_end-simple_model_start,
    ' seconds.')
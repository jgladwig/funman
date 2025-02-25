import json
import logging
import sys
import threading
from functools import partial
from typing import Callable, Optional

from pysmt.logics import QF_NRA
from pysmt.shortcuts import And, Solver

from funman.representation.representation import (
    LABEL_TRUE,
    ParameterSpace,
    Point,
)
from funman.utils.smtlib_utils import smtlibscript_from_formula_list

# import funman.search as search
from .search import Search, SearchEpisode

# from funman.utils.sympy_utils import sympy_to_pysmt, to_sympy


l = logging.getLogger(__file__)
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
l.setLevel(logging.INFO)


class SMTCheck(Search):
    def search(
        self,
        problem,
        config: Optional["FUNMANConfig"] = None,
        haltEvent: Optional[threading.Event] = None,
        resultsCallback: Optional[Callable[["ParameterSpace"], None]] = None,
    ) -> "SearchEpisode":
        parameter_space = ParameterSpace(
            num_dimensions=problem.num_dimensions()
        )
        models = {}
        consistent = {}
        for (
            structural_configuration
        ) in problem._smt_encoder._timed_model_elements["configurations"]:
            l.info(f"Solving configuration: {structural_configuration}")
            problem._encode_timed(
                structural_configuration["num_steps"],
                problem._smt_encoder._timed_model_elements["step_sizes"].index(
                    structural_configuration["step_size"]
                ),
                config,
            )
            episode = SearchEpisode(
                config=config,
                problem=problem,
                structural_configuration=structural_configuration,
            )
            # self._initialize_encoding(solver, episode, box_timepoint, box)
            result = self.expand(
                problem,
                episode,
                parameter_space,
                list(range(structural_configuration["num_steps"] + 1)),
            )

            result_dict = result.to_dict() if result else None
            l.info(f"Result: {json.dumps(result_dict, indent=4)}")
            if result_dict is not None:
                parameter_values = {
                    k: v
                    for k, v in result_dict.items()
                    # if k in [p.name for p in problem.parameters]
                }
                for k, v in structural_configuration.items():
                    parameter_values[k] = v
                point = Point(values=parameter_values, label=LABEL_TRUE)
                models[point] = result
                consistent[point] = result_dict
                parameter_space.true_points.append(point)
            if resultsCallback:
                resultsCallback(parameter_space)

        return parameter_space, models, consistent

    def expand(self, problem, episode, parameter_space, timepoints):
        if episode.config.solver == "dreal":
            opts = {
                "dreal_precision": episode.config.dreal_precision,
                "dreal_log_level": episode.config.dreal_log_level,
                "dreal_mcts": episode.config.dreal_mcts,
            }
        else:
            opts = {}
        with Solver(
            name=episode.config.solver,
            logic=QF_NRA,
            solver_options=opts,
        ) as s:
            formula = And(
                problem._model_encoding.encoding(
                    episode.problem._model_encoding._encoder.encode_model_layer,
                    layers=timepoints,
                ),
                problem._query_encoding.encoding(
                    partial(
                        episode.problem._query_encoding._encoder.encode_query_layer,
                        episode.problem.query,
                    ),
                    layers=timepoints,
                ),
                problem._smt_encoder.box_to_smt(
                    episode._initial_box().project(
                        episode.problem.model_parameters()
                    )
                ),
            )
            if episode.config.simplify_query:
                formula = formula.substitute(
                    problem._smt_encoder._timed_model_elements[
                        "time_step_substitutions"
                    ][0]
                ).simplify()
                # fs = to_sympy(formula.serialize(), ["beta"])
                # from sympy import simplify, factor, cancel, nsimplify
                # ps = sympy_to_pysmt(fs)

            s.add_assertion(formula)
            if episode.config.save_smtlib:
                self.store_smtlib(
                    formula,
                    filename=f"dbg_steps{episode.structural_configuration['num_steps']}_ssize{episode.structural_configuration['step_size']}.smt2",
                )
            result = s.solve()
            # print(episode.structural_configuration)
            if result:
                result = s.get_model()
        return result

    def store_smtlib(self, formula, filename="dbg.smt2"):
        with open(filename, "w") as f:
            smtlibscript_from_formula_list(
                [formula],
                logic=QF_NRA,
            ).serialize(f, daggify=False)

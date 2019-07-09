from pathlib import Path
from typing import List, NamedTuple, Tuple, Union

from pysmt.fnode import FNode
from pysmt.shortcuts import EqualsOrIff, get_env, TRUE

from cosa.encoders.template import ModelParser
from cosa.encoders.formulae import StringParser
from cosa.representation import HTS, TS
from cosa.utils.formula_mngm import get_free_variables

class InitParser(ModelParser):
    extensions = ['init']
    name = "INIT"

    def __init__(self):
        self.parser = StringParser()
        self._pysmt_formula_manager = get_env().formula_manager

    # implementing ModelParser interface
    @staticmethod
    def get_extensions():
        return InitParser.extensions

    def is_available(self):
        return True

    def get_model_info(self):
        return None

    def parse_string(self, string:str)->Union[FNode, None]:
        if '=' not in string:
            raise RuntimeError("Expecting a single equality but got: {}".format(string))

        split = string.split("=")
        if len(split) > 2:
            raise RuntimeError("Expecting exactly one equality but got: {}".format(string))

        lhs, rhs = split

        lhs = sparser.parse_formula(lhs)
        rhs = sparser.parse_formula(rhs)

        for fv in get_free_variables(lhs):
            if not self._pysmt_formula_manager.is_state_var(fv):
                return None

        if not rhs.is_constant():
            raise RuntimeError("Expecting a constant on the right side but got: {}".format(rhs))

        return EqualsOrIff(lhs, rhs)

    def parse_file(self,
                   filepath:Path,
                   config:NamedTuple,
                   flags:str=None)->Tuple[HTS, List[FNode], List[FNode]]:

        hts = HTS(filepath.name)
        ts = TS("TS %s"%filepath.name)

        init = []

        with filepath.open("w") as f:
            contents = f.read()
            for line in contents:
                line = line.strip()
                if not line:
                    continue
                else:
                    res = self.parse_string(line)
                    if res is not None:
                        init.append(res)

        ts.init = And(init)
        ts.invar = TRUE()
        ts.trans = TRUE()
        hts.add_ts(ts)

        return hts


#!/usr/bin/env python

# Copyright 2018 Cristian Mattarei
#
# Licensed under the modified BSD (3-clause BSD) License.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import coreir
import argparse
import os
import pickle

from argparse import RawTextHelpFormatter

from cosa.analyzers.dispatcher import ProblemSolver
from cosa.analyzers.bmc import BMC, BMCConfig
from cosa.analyzers.bmc_liveness import BMCLiveness
from cosa.utils.logger import Logger
from cosa.printers import PrintersFactory, PrinterType, SMVHTSPrinter
from cosa.encoders.explicit_transition_system import ExplicitTSParser
from cosa.encoders.symbolic_transition_system import SymbolicTSParser
from cosa.encoders.coreir import CoreIRParser
from cosa.encoders.formulae import StringParser
from cosa.encoders.miter import Miter
from cosa.problem import Problems, VerificationStatus, VerificationType
from cosa.transition_systems import HTS

from pysmt.shortcuts import TRUE


class Config(object):
    parser = None
    strfiles = None
    verbosity = 1
    simulate = False
    bmc_length = 10
    bmc_length_min = 0
    safety = None
    liveness = None
    eventually = None
    properties = None
    lemmas = None
    assumptions = None
    equivalence = None
    symbolic_init = None
    fsm_check = False
    full_trace = False
    prefix = None
    run_passes = False
    printer = None
    translate = None
    smt2file = None
    strategy = None
    boolean = None
    abstract_clock = False
    skip_solving = False
    pickle_file = None
    solver_name = None
    vcd = False
    prove = False

    def __init__(self):
        PrintersFactory.init_printers()

        self.parser = None
        self.strfiles = None
        self.verbosity = 1
        self.simulate = False
        self.bmc_length = 10
        self.bmc_length_min = 0
        self.safety = None
        self.liveness = None
        self.eventually = None
        self.properties = None
        self.lemmas = None
        self.assumptions = None
        self.equivalence = None
        self.symbolic_init = False
        self.fsm_check = False
        self.full_trace = False
        self.prefix = None
        self.run_passes = False
        self.printer = PrintersFactory.get_default().get_name()
        self.translate = None
        self.smt2file = None
        self.strategy = BMCConfig.get_strategies()[0][0]
        self.boolean = False
        self.abstract_clock = False
        self.skip_solving = False
        self.pickle_file = None
        self.solver_name = "msat"
        self.vcd = False
        self.prove = False

def trace_printed(msg, hr_trace, vcd_trace):
    vcd_msg = ""
    if vcd_trace:
        vcd_msg = " and in \"%s\""%(vcd_trace)
    Logger.log("%s stored in \"%s\"%s"%(msg, hr_trace, vcd_msg), 0)

def print_trace(msg, trace, index, prefix):
    trace_hr, trace_vcd = trace

    hr_trace_file = None
    vcd_trace_file = None

    if prefix:
        if trace_hr:
            hr_trace_file = "%s-%s.txt"%(prefix, index)
            with open(hr_trace_file, "w") as f:
                f.write(trace_hr)

        if trace_vcd:
            vcd_trace_file = "%s-%s.vcd"%(prefix, index)
            with open(vcd_trace_file, "w") as f:
                f.write(trace_vcd)

        trace_printed(msg, hr_trace_file, vcd_trace_file)

    else:
        Logger.log("%s:"%msg, 0)
        Logger.log(trace_hr, 0)

def get_file_flags(strfile):
    if "[" not in strfile:
        return (strfile, [])
    
    (strfile, flags) = (strfile[:strfile.index("[")], strfile[strfile.index("[")+1:strfile.index("]")].split(","))
    return (strfile, flags)
                        
def run_verification(config):
    Logger.verbosity = config.verbosity

    coreir_parser = None
    ets_parser = None
    sts_parser = None

    hts = HTS("Top level")

    if config.strfiles[0][-4:] != ".pkl":
        ps = ProblemSolver()
        hts = ps.parse_model("./", config.strfiles, config.abstract_clock, config.symbolic_init)
        config.parser = ps.parser

        if config.pickle_file:
            Logger.msg("Pickling model to %s\n"%(config.pickle_file), 1)
            sys.setrecursionlimit(50000)
            with open(config.pickle_file, "wb") as f:
                pickle.dump(hts, f)
                f.close()
            sys.setrecursionlimit(1000)
    else:
        if config.pickle_file:
            raise RuntimeError("Don't need to re-pickle the input file %s"%(config.strfile))

        Logger.msg("Loading pickle file %s\n"%(config.strfile), 0)
        f = open(config.strfile, "rb")
        hts = pickle.load(f)
        f.close()
        Logger.log("DONE", 0)

    printsmv = True

    bmc_config = BMCConfig()

    sparser = StringParser()
    sparser.remap_or2an = config.parser.remap_or2an

    # if equivalence checking wait to add assumptions to combined system
    if config.assumptions is not None and config.equivalence is None:
        Logger.log("Adding %d assumptions... "%len(config.assumptions), 1)
        assumps = [t[1] for t in sparser.parse_formulae(config.assumptions)]
        hts.assumptions = assumps

    lemmas = None
    if config.lemmas is not None:
        Logger.log("Adding %d lemmas... "%len(config.lemmas), 1)
        parsed_formulae = sparser.parse_formulae(config.lemmas)
        if list(set([t[2] for t in parsed_formulae]))[0][0] != False:
            Logger.error("Lemmas do not support \"next\" operators")
        lemmas = [t[1] for t in parsed_formulae]


    bmc_config.smt2file = config.smt2file

    bmc_config.full_trace = config.full_trace
    bmc_config.prefix = config.prefix
    bmc_config.strategy = config.strategy
    bmc_config.skip_solving = config.skip_solving
    bmc_config.map_function = config.parser.remap_an2or
    bmc_config.solver_name = config.solver_name
    bmc_config.vcd_trace = config.vcd
    bmc_config.prove = config.prove

    if config.liveness or config.eventually:
        bmc_liveness = BMCLiveness(hts, bmc_config)
    else:
        bmc = BMC(hts, bmc_config)

    if config.translate:
        Logger.log("Writing system to \"%s\""%(config.translate), 0)
        printer = PrintersFactory.printer_by_name(config.printer)

        properties = None
        if config.properties:
            properties = sparser.parse_formulae(config.properties)

        with open(config.translate, "w") as f:
            f.write(printer.print_hts(hts, properties))

    if config.simulate:
        count = 0
        if config.properties is None:
            props = [("True", TRUE(), None)]
        else:
            props = sparser.parse_formulae(config.properties)
        for (strprop, prop, types) in props:
            Logger.log("Simulation for property \"%s\":"%(strprop), 0)
            res, trace = bmc.simulate(prop, config.bmc_length)
            if res == VerificationStatus.TRUE:
                count += 1
                print_trace("Execution", trace, count, config.prefix)

    if config.safety:
        count = 0
        list_status = []
        for (strprop, prop, types) in sparser.parse_formulae(config.properties):
            Logger.log("Safety verification for property \"%s\":"%(strprop), 0)
            res, trace, t = bmc.safety(prop, config.bmc_length, config.bmc_length_min, lemmas)
            Logger.log("Property is %s"%res, 0)
            if res == VerificationStatus.FALSE:
                count += 1
                print_trace("Counterexample", trace, count, config.prefix)

            list_status.append(res)

        return list_status

    if config.liveness:
        count = 0
        list_status = []
        for (strprop, prop, types) in sparser.parse_formulae(config.properties):
            Logger.log("Liveness verification for property \"%s\":"%(strprop), 0)
            res, trace = bmc_liveness.liveness(prop, config.bmc_length, config.bmc_length_min, lemmas)
            Logger.log("Property is %s"%res, 0)
            if res == VerificationStatus.FALSE:
                count += 1
                print_trace("Counterexample", trace, count, config.prefix)

            list_status.append(res)

        return list_status

    if config.eventually:
        count = 0
        list_status = []
        for (strprop, prop, types) in sparser.parse_formulae(config.properties):
            Logger.log("Eventually verification for property \"%s\":"%(strprop), 0)
            res, trace = bmc_liveness.eventually(prop, config.bmc_length, config.bmc_length_min, lemmas)
            Logger.log("Property is %s"%res, 0)
            if res == VerificationStatus.FALSE:
                count += 1
                print_trace("Counterexample", trace, count, config.prefix)

            list_status.append(res)

        return list_status
    
    if config.equivalence:
        parser2 = CoreIRParser(config.abstract_clock, config.symbolic_init)

        if config.run_passes:
            Logger.log("Running passes:", 0)
            parser2.run_passes()

        Logger.msg("Parsing file \"%s\"... "%(config.equivalence), 0)
        hts2 = parser2.parse_file(config.equivalence)
        Logger.log("DONE", 0)

        symb = " (symbolic init)" if config.symbolic_init else ""
        Logger.log("Equivalence checking%s with k=%s:"%(symb, config.bmc_length), 0)

        if Logger.level(1):
            print(hts2.print_statistics("System 2"))

        # TODO: Make incremental solving optional
        htseq, miter_out = Miter.combine_systems(hts, hts2, config.bmc_length, config.symbolic_init, config.properties, True)

        if config.assumptions is not None:
            Logger.log("Adding %d assumptions to combined system... "%len(config.assumptions), 1)
            assumps = [t[1] for t in sparser.parse_formulae(config.assumptions)]
            htseq.assumptions = assumps

        # create bmc object for combined system
        bmcseq = BMC(htseq, bmc_config)
        res, trace, t = bmcseq.safety(miter_out, config.bmc_length, config.bmc_length_min, lemmas)

        if res == VerificationStatus.FALSE:
            Logger.log("Systems are not equivalent", 0)
            print_trace("Counterexample", trace, 1, config.prefix)
        elif res == VerificationStatus.UNK:
            if config.symbolic_init:
                # strong equivalence with symbolic initial state
                Logger.log("Systems are equivalent.", 0)
            else:
                Logger.log("Systems are sequentially equivalent up to k=%i"%t, 0)
        else:
            Logger.log("Systems are equivalent at k=%i"%t, 0)


    if config.fsm_check:
        Logger.log("Checking FSM:", 0)

        bmc.fsm_check()


def run_problems(problems, config):
    Logger.verbosity = config.verbosity
    pbms = Problems()
    psol = ProblemSolver()
    pbms.load_problems(problems)
    psol.solve_problems(pbms, config)

    Logger.log("\n*** SUMMARY ***", 0)

    list_status = []
    
    for pbm in pbms.problems:
        unk_k = "" if pbm.status != VerificationStatus.UNK else "\nBMC depth: %s"%pbm.bmc_length
        Logger.log("\n** Problem %s **"%(pbm.name), 0)
        Logger.log("Description: %s"%(pbm.description), 0)
        Logger.log("Result: %s%s"%(pbm.status, unk_k), 0)
        list_status.append(pbm.status)
        if (pbm.verification != VerificationType.SIMULATION) and (pbm.status == VerificationStatus.FALSE):
            print_trace("Counterexample", pbm.trace, pbm.name, config.prefix)

        if (pbm.verification == VerificationType.SIMULATION) and (pbm.status == VerificationStatus.TRUE):
            print_trace("Execution", pbm.trace, pbm.name, config.prefix)
            
    return list_status
            
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='CoreIR Symbolic Analyzer.', formatter_class=RawTextHelpFormatter)

    config = Config()

    # Main inputs

    in_options = parser.add_argument_group('input options')
    
    in_options.set_defaults(input_files=None)
    in_options.add_argument('-i', '--input_files', metavar='<input files>', type=str, required=False,
                        help='comma separated list of input files.')

    in_options.set_defaults(problems=None)
    in_options.add_argument('--problems', metavar='<problems file>', type=str, required=False,
                       help='problems file describing the verifications to be performed.')

    # Verification Options

    ver_options = parser.add_argument_group('analysis')
    
    ver_options.set_defaults(safety=False)
    ver_options.add_argument('--safety', dest='safety', action='store_true',
                       help='safety (G) verification using BMC.')

    ver_options.set_defaults(liveness=False)
    ver_options.add_argument('--liveness', dest='liveness', action='store_true',
                       help='liveness (GF) verification using BMC.')

    ver_options.set_defaults(eventually=False)
    ver_options.add_argument('--eventually', dest='eventually', action='store_true',
                       help='eventually (F) verification using BMC.')

    ver_options.set_defaults(simulate=False)
    ver_options.add_argument('--simulate', dest='simulate', action='store_true',
                       help='simulate system using BMC.')

    ver_options.set_defaults(equivalence=None)
    ver_options.add_argument('--equivalence', metavar='<input files>', type=str, required=False,
                       help='equivalence checking using BMC.')

    ver_options.set_defaults(fsm_check=False)
    ver_options.add_argument('--fsm-check', dest='fsm_check', action='store_true',
                       help='check if the state machine is deterministic.')
    
    # Verification parameters

    ver_params = parser.add_argument_group('verification parameters')
    
    ver_params.set_defaults(properties=None)
    ver_params.add_argument('-p', '--properties', metavar='<invar list>', type=str, required=False,
                       help='comma separated list of properties.')

    ver_params.set_defaults(bmc_length=config.bmc_length)
    ver_params.add_argument('-k', '--bmc-length', metavar='<BMC length>', type=int, required=False,
                        help="depth of BMC unrolling. (Default is \"%s\")"%config.bmc_length)

    ver_params.set_defaults(bmc_length_min=config.bmc_length_min)
    ver_params.add_argument('-km', '--bmc-length-min', metavar='<BMC length>', type=int, required=False,
                        help="minimum depth of BMC unrolling. (Default is \"%s\")"%config.bmc_length_min)
    
    ver_params.set_defaults(lemmas=None)
    ver_params.add_argument('-l', '--lemmas', metavar='<invar list>', type=str, required=False,
                       help='comma separated list of lemmas.')

    ver_params.set_defaults(assumptions=None)
    ver_params.add_argument('-a', '--assumptions', metavar='<invar assumptions list>', type=str, required=False,
                       help='comma separated list of invariant assumptions.')

    ver_params.set_defaults(prove=False)
    ver_params.add_argument('--prove', dest='prove', action='store_true',
                       help='use indution to prove the satisfiability of the property.')

    strategies = [" - \"%s\": %s"%(x[0], x[1]) for x in BMCConfig.get_strategies()]
    defstrategy = BMCConfig.get_strategies()[0][0]
    ver_params.set_defaults(strategy=defstrategy)
    ver_params.add_argument('--strategy', metavar='strategy', type=str, nargs='?',
                        help='select the BMC strategy between (Default is \"%s\"):\n%s'%(defstrategy, "\n".join(strategies)))

    ver_params.set_defaults(solver_name=config.solver_name)
    ver_params.add_argument('--solver-name', metavar='<Solver Name>', type=str, required=False,
                        help="name of SMT solver to be use. (Default is \"%s\")"%config.solver_name)
    
    # Encoding parameters

    enc_params = parser.add_argument_group('encoding')
    
    enc_params.set_defaults(abstract_clock=False)
    enc_params.add_argument('--abstract-clock', dest='abstract_clock', action='store_true',
                       help='abstracts the clock behavior.')

    enc_params.set_defaults(symbolic_init=config.symbolic_init)
    enc_params.add_argument('--symbolic-init', dest='symbolic_init', action='store_true',
                       help='symbolic inititial state for equivalence checking. (Default is \"%s\")'%config.symbolic_init)

    enc_params.set_defaults(boolean=config.boolean)
    enc_params.add_argument('--boolean', dest='boolean', action='store_true',
                        help='interprets single bits as Booleans instead of 1-bit Bitvector. (Default is \"%s\")'%config.boolean)

    # enc_params.set_defaults(run_passes=config.run_passes)
    # enc_params.add_argument('--run-passes', dest='run_passes', action='store_true',
    #                     help='run necessary passes to process the CoreIR file. (Default is \"%s\")'%config.run_passes)

    enc_params.set_defaults(full_trace=config.full_trace)
    enc_params.add_argument('--full-trace', dest='full_trace', action='store_true',
                       help="show all variables in the counterexamples. (Default is \"%s\")"%config.full_trace)

    # Printing parameters

    print_params = parser.add_argument_group('trace printing')
    
    print_params.set_defaults(prefix=None)
    print_params.add_argument('--prefix', metavar='<prefix location>', type=str, required=False,
                       help='write the counterexamples with a specified location prefix.')
    
    print_params.set_defaults(vcd=False)
    print_params.add_argument('--vcd', dest='vcd', action='store_true',
                       help='generate traces also in vcd format.')

    # Translation parameters

    trans_params = parser.add_argument_group('translation')
    
    trans_params.set_defaults(smt2=None)
    trans_params.add_argument('--smt2', metavar='<smt-lib2 file>', type=str, required=False,
                       help='generates the smtlib2 encoding for a BMC call.')

    trans_params.set_defaults(translate=None)
    trans_params.add_argument('--translate', metavar='<output file>', type=str, required=False,
                       help='translate input file.')
    
    printers = [" - \"%s\": %s"%(x.get_name(), x.get_desc()) for x in PrintersFactory.get_printers_by_type(PrinterType.TRANSSYS)]

    trans_params.set_defaults(printer=config.printer)
    trans_params.add_argument('--printer', metavar='printer', type=str, nargs='?',
                        help='select the printer between (Default is \"%s\"):\n%s'%(config.printer, "\n".join(printers)))

    trans_params.set_defaults(skip_solving=False)
    trans_params.add_argument('--skip-solving', dest='skip_solving', action='store_true',
                        help='does not call the solver (used with --smt2 or --translate parameters).')

    trans_params.set_defaults(pickle=None)
    trans_params.add_argument('--pickle', metavar='<pickle file>', type=str, required=False,
                       help='pickles the transition system to be loaded later.')

    # Debugging

    deb_params = parser.add_argument_group('verbosity')
    
    deb_params.set_defaults(verbosity=config.verbosity)
    deb_params.add_argument('-v', dest='verbosity', metavar="<integer level>", type=int,
                        help="verbosity level. (Default is \"%s\")"%config.verbosity)

    deb_params.set_defaults(debug=False)
    deb_params.add_argument('--debug', dest='debug', action='store_true',
                       help='enables debug mode.')

    args = parser.parse_args()

    config.strfiles = args.input_files
    config.simulate = args.simulate
    config.safety = args.safety
    config.liveness = args.liveness
    config.eventually = args.eventually
    config.properties = args.properties
    config.lemmas = args.lemmas
    config.assumptions = args.assumptions
    config.equivalence = args.equivalence
    config.symbolic_init = args.symbolic_init
    config.fsm_check = args.fsm_check
    config.bmc_length = args.bmc_length
    config.bmc_length_min = args.bmc_length_min
    config.full_trace = args.full_trace
    config.prefix = args.prefix
    # config.run_passes = args.run_passes
    config.translate = args.translate
    config.smt2file = args.smt2
    config.strategy = args.strategy
    config.skip_solving = args.skip_solving
    config.pickle_file = args.pickle
    config.abstract_clock = args.abstract_clock
    config.boolean = args.boolean
    config.verbosity = args.verbosity
    config.vcd = args.vcd
    config.prove = args.prove
    config.solver_name = args.solver_name

    if len(sys.argv)==1:
        parser.print_help()
        sys.exit(1)

    if args.problems:
        if args.debug:
            run_problems(args.problems, config)
        else:
            try:
                run_problems(args.problems, config)
            except Exception as e:
                Logger.msg(str(e), 0)
        sys.exit(0)

    if (args.problems is None) and (args.input_files is None):
        Logger.error("No input files provided")

    if args.printer in [str(x.get_name()) for x in PrintersFactory.get_printers_by_type(PrinterType.TRANSSYS)]:
        config.printer = args.printer
    else:
        Logger.error("Printer \"%s\" not found"%(args.printer))

    if args.strategy not in [s[0] for s in BMCConfig.get_strategies()]:
        Logger.error("Strategy \"%s\" not found"%(args.strategy))

    if not(config.simulate or \
           (config.safety) or \
           (config.liveness) or \
           (config.eventually) or \
           (config.equivalence is not None) or\
           (config.translate is not None) or\
           (config.fsm_check)):
        Logger.error("Analysis selection is necessary")

    if config.safety and (config.properties is None):
        Logger.error("Safety verification requires at least a property")

    if config.safety and (config.properties is None):
        Logger.error("Safety verification requires at least a property")

    if config.liveness and (config.properties is None):
        Logger.error("Liveness verification requires at least a property")

    if config.eventually and (config.properties is None):
        Logger.error("Eventually verification requires at least a property")
        
    parsing_defs = [config.properties, config.lemmas, config.assumptions]
    for i in range(len(parsing_defs)):
        if parsing_defs[i] is not None:
            if os.path.isfile(parsing_defs[i]):
                with open(parsing_defs[i]) as f:
                    parsing_defs[i] = [p.strip() for p in f.read().strip().split("\n")]
            else:
                parsing_defs[i] = [p.strip() for p in parsing_defs[i].split(",")]

    [config.properties, config.lemmas, config.assumptions] = parsing_defs

    if args.debug:
        run_verification(config)
    else:
        try:
            run_verification(config)
        except Exception as e:
            Logger.msg(str(e), 0)
    


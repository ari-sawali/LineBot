# -*- coding: utf-8 -*-
from multiprocessing import Process, Queue as MultiQueue
import Queue

from enum import Enum
import re
import time

from error import error

from math import *
import sympy

class calc_type(Enum):
    unknown = -1
    normal = 0
    polynomial_factorization = 1
    algebraic_equations = 2

class text_calculator(object):
    # IMPORTANT: always timeout on non calculatable text (basic)

    def __init__(self, timeout=15.0):
        self._queue = MultiQueue()
        self._timeout = timeout

        self._equation_keyword = '=0'

    def calculate(self, text, debug=False, sympy_calc=False):
        result_data = calc_result_data(text)
        init_time = time.time()
        
        if text_calculator.is_non_calc(text):
            result_data.auto_record_time(init_time)
            return result_data

        try:
            if sympy_calc:
                calc_type_var = self._sympy_calculate_type(text)

                if calc_type_var == calc_type.unknown:
                    result_data.success = False
                    result_data.calc_result = error.string_calculator.unknown_calculate_type()

                    return result_data

                calc_proc = self._get_calculate_proc(calc_type_var, (init_time, text, debug, self._queue))
            else:
                calc_proc = self._get_calculate_proc(calc_type.normal, (init_time, text, debug, self._queue))
            calc_proc.start()

            result_data = self._queue.get(True, self._timeout)
        except Queue.Empty:
            result_data.auto_record_time(init_time)
            calc_proc.terminate()

            result_data.success = False
            result_data.timeout = True
            result_data.calc_result = error.string_calculator.calculation_timeout(self._timeout)

            if debug:
                print result_data.get_debug_text().encode('utf-8')

        return result_data

    def _get_calculate_proc(self, type_enum, args_tuple):
        """
        args_tuple: (init_time, text, debug, self._queue)
        """
        if type_enum == calc_type.normal:
            return Process(target=self._basic_calc_proc, args=args_tuple)
        elif type_enum == calc_type.algebraic_equations:
            return Process(target=self._algebraic_equations, args=args_tuple)
        elif type_enum == calc_type.polynomial_factorization:
            return Process(target=self._polynomial_factorization, args=args_tuple)
        else:
            raise Exception('Process not defined.')

    def _basic_calc_proc(self, init_time, text, debug, queue):
        result_data = calc_result_data(text)
        try:
            result = ''
            start_time = init_time

            if 'result=' not in text:
                exec('result={}'.format(text))
            else:
                exec(text)

            result_data.auto_record_time(start_time)

            if isinstance(result, (float, int, long)):
                if isinstance(result, long) and result.bit_length() > 333:
                    result_data.over_length = True

                start_time = time.time()
                
                _calc_result = str(result)

                result_data.auto_record_time(start_time)
                
                result_data.success = result_data.formula_str != _calc_result
                result_data.calc_result = _calc_result
            else:
                result_data.success = False
                result_data.calc_result = error.string_calculator.result_is_not_numeric(text)
                if debug:
                    print result_data.get_debug_text().encode('utf-8')

        except OverflowError:
            result_data.success = False
            result_data.calc_result = error.string_calculator.overflow()
                
            result_data.auto_record_time(start_time)

            if debug:
                print result_data.get_debug_text().encode('utf-8')

        except Exception as ex:
            result_data.success = False
            result_data.calc_result = ex.message
                
            result_data.auto_record_time(start_time)

            if debug:
                print result_data.get_debug_text().encode('utf-8')

        queue.put(result_data)

    def _algebraic_equations(self, init_time, text, debug, queue):
        # TODO: wrong format error handling
        result_data = calc_result_data(text, True)
        text = text_calculator.formula_to_py(result_data.formula_str)
        try:
            text_line = text.split('\n')
            
            if len(text_line) < 2:
                result_data.success = False
                result_data.calc_result = error.string_calculator.wrong_format_to_calc_equations()
                queue.put(result_data)
            
            var_init = text_line[0].replace(' ', '')
            var_init_symbol = ' '.join(var_init.split(','))
            formula_list = text_line[1:]

            if any((not formula.endswith(self._equation_keyword)) for formula in formula_list):
                result_data.success = False
                result_data.calc_result = error.string_calculator.wrong_format_to_calc_equations()
                queue.put(result_data)
            
            formula_list_replaced = [text_calculator.formula_to_py(eq).replace(self._equation_keyword, '') for eq in text_line[1:]]

            exec_py = '{} = sympy.symbols(\'{}\', real=True)'.format(var_init, var_init_symbol)
            exec_py += '\nresult = sympy.solve(formula_list_replaced, {})'.format(var_init)
            print exec_py

            start_time = init_time
            exec(exec_py) in globals(), locals()

            result_data.auto_record_time(start_time)

            result_data.success = True

            start_time = time.time()
            str_calc_result = str(result)
            result_data.latex = sympy.latex(result)
            result_data.auto_record_time(start_time)
            
            result_data.formula_str = '\n'.join(formula_list)
            result_data.calc_result = str_calc_result

        except Exception as ex:
            result_data.success = False
            result_data.calc_result = '{} - {}'.format(type(ex), ex.message)
                
            result_data.auto_record_time(start_time)

            if debug:
                print result_data.get_debug_text().encode('utf-8')
            
        queue.put(result_data)

    def _polynomial_factorization(self, init_time, text, debug, queue):
        result_data = calc_result_data(text, True)
        text = text_calculator.formula_to_py(result_data.formula_str)
        try:
            start_time = init_time
            exec('result = sympy.factor(text)')
            result_data.auto_record_time(start_time)

            result_data.success = True

            start_time = time.time()
            str_calc_result = str(result)
            result_data.latex = sympy.latex(result)
            result_data.auto_record_time(start_time)
            
            result_data.calc_result = str_calc_result

        except Exception as ex:
            result_data.success = False
            result_data.calc_result = ex.message
                
            result_data.auto_record_time(start_time)

            if debug:
                print result_data.get_debug_text().encode('utf-8')
            
        queue.put(result_data)

    def _sympy_calculate_type(self, text):
        if self._equation_keyword in text and '\n' in text:
            return calc_type.algebraic_equations
        elif self._equation_keyword not in text and '\n' not in text:
            return calc_type.polynomial_factorization
        else:
            return calc_type.unknown

    @staticmethod
    def remove_non_digit(text):
        import string
        allchars = ''.join(chr(i) for i in xrange(256))
        identity = string.maketrans('', '')
        nondigits = allchars.translate(identity, string.digits)
        return text.translate(identity, nondigits)

    @staticmethod
    def is_non_calc(text):
        try:
            text.decode('ascii')
            return (text.startswith('0') and '.' not in text) or text.startswith('+') or text.endswith('.')
        except UnicodeDecodeError:
            return True
        except UnicodeEncodeError:
            return True
        else:
            return False

    @staticmethod
    def formula_to_py(text):
        regex = ur"([\d.]*)([\d]*[\w]*)([+\-*/]?)"
        
        def add_star(match):
            if match.group(1) != '' and match.group(2) != '':
                return u'{}*{}{}'.format(match.group(1), match.group(2), match.group(3))
            else:
                return match.group()
        
        return re.sub(regex, add_star, text)

class calc_result_data(object):
    def __init__(self, formula_str, latex_avaliable=False):
        self._formula_str = formula_str
        self._calc_result = None
        self._latex = None
        self._calc_time = -1.0
        self._type_cast_time = -1.0
        self._timeout = False
        self._success = False
        self._over_length = False
        self._latex_avaliable = latex_avaliable

    @property
    def formula_str(self):
        return self._formula_str

    @formula_str.setter
    def formula_str(self, value):
        if isinstance(value, (str, unicode)):
            self._formula_str = value
        else:
            raise Exception('Calculate result should be string or unicode.')
    
    @property
    def calc_result(self):
        return self._calc_result

    @calc_result.setter
    def calc_result(self, value):
        if isinstance(value, (str, unicode)):
            self._calc_result = value
        else:
            raise Exception('Calculate result should be string or unicode.')
    
    @property
    def latex(self):
        return self._latex

    @latex.setter
    def latex(self, value):
        if isinstance(value, str):
            self._latex = value
        else:
            raise Exception('LaTeX should be string.')

    @property
    def calc_time(self):
        return self._calc_time

    @calc_time.setter
    def calc_time(self, value):
        self._calc_time = value
    
    @property
    def type_cast_time(self):
        return self._type_cast_time

    @type_cast_time.setter
    def type_cast_time(self, value):
        self._type_cast_time = value
    
    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        self._timeout = value
        
    @property
    def success(self):
        return self._success

    @success.setter
    def success(self, value):
        self._success = value

    @property
    def latex_avaliable(self):
        return self._latex_avaliable and self._latex is not None

    @latex_avaliable.setter
    def latex_avaliable(self, value):
        self._latex_avaliable = value

    @property
    def over_length(self):
        return self._over_length

    @over_length.setter
    def over_length(self, value):
        self._over_length = value

    def auto_record_time(self, start_time):
        if self._calc_time == -1.0:
            self._calc_time = time.time() - start_time
        elif self._type_cast_time == -1.0:
            if self._calc_time == -1.0:
                self._calc_time = time.time() - start_time
            else:
                self._type_cast_time = time.time() - start_time

    def get_basic_text(self):
        return u'算式:\n{}\n結果:\n{}\n計算時間:\n{}\n顯示時間:\n{}'.format(
            self._formula_str,
            self._calc_result,
            u'(未執行)' if self._calc_time == -1.0 else u'{:f}秒'.format(self._calc_time),
            u'(未執行)' if self._type_cast_time == -1.0 else u'{:f}秒'.format(self._type_cast_time))

    def get_debug_text(self):
        return u'計算{}\n\n{}'.format(
            u'成功' if self._success else u'失敗', 
            self.get_basic_text())


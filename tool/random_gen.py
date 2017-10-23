# coding: utf-8

import random
import string

class random_drawer(object):
    @staticmethod
    def draw_number(start, end):
        start = int(start)
        end = int(end)
        return random.randint(start, end)

    @staticmethod
    def draw_number_string(start, end):
        result = random_drawer.draw_number(start, end)
        return u'抽選範圍【{}~{}】\n抽選結果【{}】'.format(start, end, result)
        
    @staticmethod
    def draw_from_list(text_list):
        random.shuffle(text_list)
        return random.choice(text_list)

    @staticmethod
    def draw_text_string(text_list):
        result = random_drawer.draw_from_list(text_list)
        return u'抽選項目【{}】\n抽選結果【{}】'.format(u'、'.join(text_list), result)

    @staticmethod
    def draw_probability(probability, is_value=True):
        if is_value:
            probability /= 100.0
        return random.random() <= probability

    @staticmethod
    def draw_probability_string(probability, is_value=True, count=1, prediction_count=2):
        probability = float(probability)
        count = int(count)
        if is_value:
            probability /= 100.0
        result_list = {i: random_drawer.draw_probability(probability, False) for i in range(1, count + 1)}
        shot_count = sum(x for x in result_list.values())
        miss_count = count - shot_count

        text = u'抽選機率【{:.2%}】'.format(probability)
        text += u'\n抽選結果【中{}次 | 失{}次】'.format(shot_count, miss_count)
        text += u'\n中選位置【{}】'.format(u'、'.join([str(key) for key, value in result_list.iteritems() if value]))
        text += u'\n實際中率【{:.2%}】'.format(shot_count / float(len(result_list)))
        for i in range(prediction_count):
            prediction_probability = (1 - (1 - probability) ** (count - i)) * probability ** i
            if prediction_probability >= 0:
                text += u'\n中{}+機率【{:.2%}】'.format(i + 1, prediction_probability)

        return text

    @staticmethod
    def generate_random_string(length):
        return ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(length))
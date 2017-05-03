# -*- coding: utf-8 -*-

class error(object):

    class webpage(object):

        @staticmethod
        def no_content_at_time(content_type, timestamp):
            return 'No {type} recorded at the specified time. ({time})'.format(time=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp)),
                                                                               type=content_type)

        @staticmethod
        def no_content():
            return 'No content.'

    class main(object):
        
        @staticmethod
        def invalid_thing(name_of_thing, thing):
            return u'���X�k��{}: {}. ���˾\�ϥλ����ѡC'.format(name_of_thing, thing)

        @staticmethod
        def lack_of_thing(name_of_thing):
            return u'�����㪺{nm}�C�Эץ��z�Ҵ��Ѫ�{nm}(s)�C'.format(nm=name_of_thing)

        @staticmethod
        def no_result():
            return u'�S�����G�C'

        @staticmethod
        def restricted(permission=None):
            return u'����\��C{}'.format(
                '\n\n�ݨD�̧C�v��: {}'.format(permission) if permission is not None else '')

        @staticmethod
        def incorrect_channel(available_in_1v1=True, available_in_room=False, available_in_group=False):
            return u'�L�k�b���������W�D�ϥΡC�H�U�C�X�i�ϥΪ��W�D:\n{} {} {}'.format(
                '[ �p�T ]' if available_in_1v1 else '[ - ]',
                '[ �s�� ]' if available_in_group else '[ - ]',
                '[ �ж� ]' if available_in_room else '[ - ]')
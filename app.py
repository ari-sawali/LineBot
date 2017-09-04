# -*- coding: utf-8 -*-

# import custom module
from bot import webpage_auto_gen, game_objects
from bot.system import line_api_proc, string_can_be_int, system_data, imgur_proc

import msg_handler

import errno
import os
import sys
import tempfile
import traceback
import validators
import time
from collections import defaultdict
from urlparse import urlparse
from cgi import escape
from datetime import datetime, timedelta
from error import error
from flask import Flask, request, url_for
from math import *
import threading

# import for Oxford Dictionary
import httplib
import requests
import json

# Database import
from db import kw_dict_mgr, kwdict_col, group_ban, gb_col, message_tracker, msg_track_col, msg_event_type

# tool import
from tool import mff, random_gen, txt_calc

# games import
import game

# import LINE Messaging API
from linebot import (
    LineBotApi, WebhookHandler, exceptions
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    SourceUser, SourceGroup, SourceRoom,
    TemplateSendMessage, ConfirmTemplate, MessageTemplateAction,
    ButtonsTemplate, URITemplateAction, PostbackTemplateAction,
    CarouselTemplate, CarouselColumn, PostbackEvent,
    StickerMessage, StickerSendMessage, LocationMessage, LocationSendMessage,
    ImageMessage, VideoMessage, AudioMessage,
    UnfollowEvent, FollowEvent, JoinEvent, LeaveEvent, BeaconEvent
)

# import imgur API
from imgurpython import ImgurClient
from imgurpython.helpers.error import ImgurClientError

# Databases initialization
kwd = kw_dict_mgr("postgres", os.environ["DATABASE_URL"])
gb = group_ban("postgres", os.environ["DATABASE_URL"])
msg_track = message_tracker("postgres", os.environ["DATABASE_URL"])

# Main initialization
app = Flask(__name__)
sys_data = system_data()
game_data = game_objects()

# System initialization
MAIN_UID_OLD = 'Ud5a2b5bb5eca86342d3ed75d1d606e2c'
MAIN_UID = 'U089d534654e2c5774624e8d8c813000e'
main_silent = False

administrator = os.getenv('ADMIN', None)
group_admin = os.getenv('G_ADMIN', None)
group_mod = os.getenv('G_MOD', None)
if administrator is None:
    print('The SHA224 of ADMIN not defined. Program will be terminated.')
    sys.exit(1)
if group_admin is None:
    print('The SHA224 of G_ADMIN not defined. Program will be terminated.')
    sys.exit(1)
if group_mod is None:
    print('The SHA224 of G_MOD not defined. Program will be terminated.')
    sys.exit(1)
    
# Line Bot API instantiation
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN environment variable.')
    sys.exit(1)
api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)
line_api = line_api_proc(api)

# Imgur APi instantiation
imgur_client_id = os.getenv('IMGUR_CLIENT_ID', None)
imgur_client_secret = os.getenv('IMGUR_CLIENT_SECRET', None)
if imgur_client_id is None:
    print('Specify IMGUR_CLIENT_ID environment variable.')
    sys.exit(1)
if imgur_client_secret is None:
    print('Specify IMGUR_CLIENT_SECRET environment variable.')
    sys.exit(1)
imgur = ImgurClient(imgur_client_id, imgur_client_secret)
imgur_api = imgur_proc(imgur)


# Oxford Dictionary Environment initialization
oxford_dict_obj = msg_handler.oxford_dict('en')

# File path
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')
    
# Webpage auto generator
webpage_generator = webpage_auto_gen.webpage()

# Message handler initialization
command_executor = msg_handler.text_msg(line_api, kwd, gb, msg_track, 
                                        oxford_dict_obj, [group_mod, group_admin, administrator], sys_data, 
                                        game_data, webpage_generator, imgur_api)
game_executor = msg_handler.game_msg(game_data, line_api)

# function for create tmp dir for download content
def make_static_tmp_dir():
    try:
        os.makedirs(static_tmp_path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(static_tmp_path):
            pass
        else:
            raise

# TODO: make error become object (time, detail, url, error type)
@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        # Single Thread
        handler.handle(body, signature)

        # Multi Thread
        # HandleThread = threading.Thread(target=handler.handle, args=(body,
        # signature))
        # HandleThread.start()
    except exceptions.InvalidSignatureError:
        abort(400)

    return 'OK'

@app.route("/error", methods=['GET'])
def get_error_list():
    sys_data.view_webpage()

    error_dict = defaultdict(str)    
    error_timestamp_list = webpage_generator.error_timestamp_list()
    for timestamp in error_timestamp_list:
        error_dict[datetime.fromtimestamp(float(timestamp)).strftime('%Y-%m-%d %H:%M:%S')] = request.url_root + url_for('get_error_message', timestamp=timestamp)[1:]

    return webpage_auto_gen.webpage.html_render_error_list(sys_data.boot_up, error_dict)

@app.route("/error/<timestamp>", methods=['GET'])
def get_error_message(timestamp):
    sys_data.view_webpage()
    content = webpage_generator.get_content(webpage_auto_gen.content_type.Error, timestamp)
    return webpage_auto_gen.webpage.html_render(content, u'錯誤訊息')

@app.route("/query/<timestamp>", methods=['GET'])
def full_query(timestamp):
    sys_data.view_webpage()
    content = webpage_generator.get_content(webpage_auto_gen.content_type.Query, timestamp)
    return webpage_auto_gen.webpage.html_render(content, u'查詢結果')

@app.route("/info/<timestamp>", methods=['GET'])
def full_info(timestamp):
    sys_data.view_webpage()
    content = webpage_generator.get_content(webpage_auto_gen.content_type.Info, timestamp)
    return webpage_auto_gen.webpage.html_render(content, u'詳細資料')

@app.route("/full/<timestamp>", methods=['GET'])
def full_content(timestamp):
    sys_data.view_webpage()
    content = webpage_generator.get_content(webpage_auto_gen.content_type.Text, timestamp)
    return webpage_auto_gen.webpage.html_render(content, u'完整資訊')

@app.route("/ranking/<type>", methods=['GET'])
def full_ranking(type):
    sys_data.view_webpage()
    if type == 'user':
        content = kw_dict_mgr.list_user_created_ranking(line_api, kwd.user_created_rank(50))
    elif type == 'used':
        content = kw_dict_mgr.list_keyword_ranking(kwd.order_by_usedrank(10000))
    elif type == 'called':
        content = kw_dict_mgr.list_keyword_recently_called(kwd.recently_called(10000))
    else:
        content = error.webpage.no_content()
        
    return webpage_auto_gen.webpage.html_render(content, u'完整排名')


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    global game_data
    global command_executor
    global game_executor

    token = event.reply_token
    text = event.message.text
    src = event.source
    splitter = '\n'
    
    msg_track.log_message_activity(line_api_proc.source_channel_id(src), msg_event_type.recv_txt)

    if text == '561563ed706e6f696abbe050ad79cf334b9262da6f83bc1dcf7328f2':
        sys_data.intercept = not sys_data.intercept
        api.reply_message(token, TextSendMessage(text='Bot {}.'.format('start to intercept messages' if sys_data.intercept else 'stop intercepting messages')))
        return
    elif sys_data.intercept:
        intercept_text(event)

    if text == '43afdb2391686dd9710c3879a86c04b5c0a2fc3391ffd2c6a05e4ce0': # SHA of CALCULATOR DEBUG
        sys_data.calc_debug = not sys_data.calc_debug
        print 'Calculator debugging {}.'.format('enabled' if sys_data.calc_debug else 'disabled')

    if text == administrator:
        sys_data.silence = not sys_data.silence
        api.reply_message(token, TextSendMessage(text='Bot set to {}.'.format('Silent' if sys_data.silence else 'Active')))
        return
    elif sys_data.silence:
        return

    try:
        if text == 'ERRORERRORERRORERROR':
            raise Exception('THIS ERROR IS CREATED FOR TESTING PURPOSE.')
        elif splitter in text:
            head, cmd, oth = msg_handler.split(text, splitter, 3)

            if head == 'JC':
                params = command_executor.split_verify(cmd, splitter, oth)

                if isinstance(params, unicode):
                    api_reply(token, TextSendMessage(text=params), src)
                    return
                
                # SQL Command
                if cmd == 'S':
                    text = command_executor.S(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # ADD keyword & ADD top keyword
                elif cmd == 'A' or cmd == 'M':
                    if sys_data.sys_cmd_dict[cmd].non_user_permission_required:
                        text = command_executor.M(src, params)
                    else:
                        text = command_executor.A(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # DELETE keyword & DELETE top keyword
                elif cmd == 'D' or cmd == 'R':
                    if sys_data.sys_cmd_dict[cmd].non_user_permission_required:
                        text = command_executor.R(src, params)
                    else:
                        text = command_executor.D(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # QUERY keyword
                elif cmd == 'Q':
                    text = command_executor.Q(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # INFO of keyword
                elif cmd == 'I':
                    text = command_executor.I(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # RANKING
                elif cmd == 'K':
                    text = command_executor.K(src, params)
                    
                    api_reply(token, TextSendMessage(text=text), src)
                # SPECIAL record
                elif cmd == 'P':
                    text = command_executor.P(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # GROUP ban basic (info)
                elif cmd == 'G':
                    text = command_executor.G(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # GROUP ban advance
                elif cmd == 'GA':
                    texts = command_executor.GA(src, params)

                    api_reply(token, [TextSendMessage(text=text) for text in texts], src)
                # get CHAT id
                elif cmd == 'H':
                    output = command_executor.H(src, params)

                    api_reply(token, [TextSendMessage(text=output[0]), TextSendMessage(text=output[1])], src)
                # SHA224 generator
                elif cmd == 'SHA':
                    text = command_executor.SHA(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # Look up vocabulary in OXFORD Dictionary
                elif cmd == 'O':
                    text = command_executor.O(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # RANDOM draw
                elif cmd == 'RD':
                    text = command_executor.RD(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # last STICKER message
                elif cmd == 'STK':
                    text = command_executor.STK(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # TRANSLATE text to URL form
                elif cmd == 'T':
                    text = command_executor.T(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                else:
                    sys_data.sys_cmd_dict[cmd].count -= 1
            elif head == 'HELP':
                data = msg_handler.split(text, splitter, 2)
                sys_data.helper_cmd_dict['MFF'].count += 1

                # TODO: restruct helper
                # TODO: Helper modulize
                if data[1].upper().startswith('MFF'):
                    api_reply(token, [TextSendMessage(text=mff.mff_dmg_calc.help_code()),
                                      TextSendMessage(text=u'下則訊息是訊息範本，您可以直接將其複製，更改其內容，然後使用。或是遵照以下格式輸入資料。\n\n{代碼(參見上方)} {參數}(%)\n\n例如:\nMFF\nSKC 100%\n魔力 1090%\n魔力 10.9\n\n欲察看更多範例，請前往 https://sites.google.com/view/jellybot/mff傷害計算'),
                                      TextSendMessage(text=mff.mff_dmg_calc.help_sample())], src)
                else:
                    job = mff.mff_dmg_calc.text_job_parser(data[1])

                    dmg_calc_dict = [[u'破防前非爆擊(弱點屬性)', mff.mff_dmg_calc.dmg_weak(job)],
                                     [u'破防前爆擊(弱點屬性)', mff.mff_dmg_calc.dmg_crt_weak(job)],
                                     [u'已破防非爆擊(弱點屬性)', mff.mff_dmg_calc.dmg_break_weak(job)],
                                     [u'已破防爆擊(弱點屬性)', mff.mff_dmg_calc.dmg_break_crt_weak(job)],
                                     [u'破防前非爆擊(非弱點屬性)', mff.mff_dmg_calc.dmg(job)],
                                     [u'破防前爆擊(非弱點屬性)', mff.mff_dmg_calc.dmg_crt(job)],
                                     [u'已破防非爆擊(非弱點屬性)', mff.mff_dmg_calc.dmg_break(job)],
                                     [u'已破防爆擊(非弱點屬性)', mff.mff_dmg_calc.dmg_break_crt(job)]]

                    text = u'傷害表:'
                    for title, value in dmg_calc_dict:
                        text += u'\n\n'
                        text += u'{}\n首發: {:.0f}\n連發: {:.0f}\n累積傷害(依次): {}'.format(title,
                                                                                            value['first'],
                                                                                            value['continual'],
                                                                                            u', '.join('{:.0f}'.format(x) for x in value['list_of_sum']))
                    
                    api_reply(token, TextSendMessage(text=text), src)
            elif head == 'G':
                if cmd not in sys_data.game_cmd_dict:
                    text = error.main.invalid_thing(u'遊戲', cmd)
                    api_reply(token, TextSendMessage(text=text), src)
                    return
                
                max_prm = sys_data.game_cmd_dict[cmd].split_max
                min_prm = sys_data.game_cmd_dict[cmd].split_min
                params = msg_handler.split(oth, splitter, max_prm)

                if min_prm > len(params) - params.count(None):
                    text = error.main.lack_of_thing(u'參數')
                    api_reply(token, TextSendMessage(text=text), src)
                    return

                params.insert(0, None)

                # GAME - Rock-Paper-Scissor
                if cmd == 'RPS':
                    text = game_executor.RPS(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                else:
                    sys_data.game_cmd_dict[cmd].count -= 1

        rps_obj = game_data.get_rps(line_api_proc.source_channel_id(src))
        if rps_obj is not None:
            rps_text = minigame_rps_capturing(rps_obj, False, text, line_api_proc.source_user_id(src))
            if rps_text is not None:
                api_reply(token, TextSendMessage(text=rps_text), src)
                return

        replied = auto_reply_system(token, text, False, src)
        if not replied:
            if (text.startswith('JC ') or text.startswith('HELP ') or text.startswith('G ')) and ((' ' or '  ') in text):
                msg = u'小水母指令分隔字元已從【雙空格】修改為【換行】。'
                msg += u'\n\n如欲輸入指令，請以換行分隔指令，例如:\nJC\nA\n你！\n我？'
                msg += u'\n\n如果參數中要包含換行的話，請輸入【\\n】。\n另外，JC RD的文字抽籤中，原先以換行分隔，現在則以單空格分隔。'
                text = error.main.miscellaneous(msg)
                api_reply(token, TextSendMessage(text=text), src)
                return
            else:
                calc_result = txt_calc.text_calculator.calc(text, sys_data.calc_debug)
                if calc_result is not None:
                    sys_data.helper_cmd_dict['CALC'].count += 1
                    text = u'算式: {}\n\n計算結果: {}'.format('\n{}'.format(text) if '\n' in text else text, calc_result)

                    api_reply(token, TextSendMessage(text=text), src)
                    return
    except exceptions.LineBotApiError as ex:
        text = u'開機時間: {}\n\n'.format(sys_data.boot_up)
        text += u'LINE API發生錯誤，狀態碼: {}\n\n'.format(ex.status_code)
        for err in ex.error.details:
            text += u'錯誤內容: {}\n錯誤訊息: {}\n'.format(err.property, err.message.decode("utf-8"))

        error_msg = webpage_generator.rec_error(text, line_api_proc.source_channel_id(src))
        api_reply(token, TextSendMessage(text=error_msg), src)
    except Exception as exc:
        text = u'開機時間: {}\n\n'.format(sys_data.boot_up)
        exc_type, exc_obj, exc_tb = sys.exc_info()
        text += u'錯誤種類: {}\n\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, exc.message.decode("utf-8"))
        
        error_msg = webpage_generator.rec_error(text, line_api_proc.source_channel_id(src))
        api_reply(token, TextSendMessage(text=error_msg), src)
    return 

    if text == 'confirm':
        confirm_template = ConfirmTemplate(text='Do it?', actions=[MessageTemplateAction(label='Yes', text='Yes!'),
            MessageTemplateAction(label='No', text='No!'),])
        template_message = TemplateSendMessage(alt_text='Confirm alt text', template=confirm_template)
        api_reply(event.reply_token, template_message, src)
    elif text == 'carousel':
        carousel_template = CarouselTemplate(columns=[CarouselColumn(text='hoge1', title='fuga1', actions=[URITemplateAction(label='Go to line.me', uri='https://line.me'),
                PostbackTemplateAction(label='ping', data='ping')]),
            CarouselColumn(text='hoge2', title='fuga2', actions=[PostbackTemplateAction(label='ping with text', data='ping',
                    text='ping'),
                MessageTemplateAction(label='Translate Rice', text='米')]),])
        template_message = TemplateSendMessage(alt_text='Buttons alt text', template=carousel_template)
        api_reply(event.reply_token, template_message, src)


@handler.add(MessageEvent, message=StickerMessage)
def handle_sticker_message(event):
    package_id = event.message.package_id
    sticker_id = event.message.sticker_id
    rep = event.reply_token
    src = event.source
    cid = line_api_proc.source_channel_id(src)
    
    # TODO: Modulize handle received sticker message
    sys_data.set_last_sticker(cid, sticker_id)

    global game_data
    rps_obj = game_data.get_rps(cid)

    msg_track.log_message_activity(cid, msg_event_type.recv_stk)

    if rps_obj is not None:
        text = minigame_rps_capturing(rps_obj, True, sticker_id, line_api_proc.source_user_id(src))
        if text is not None:
            api_reply(rep, TextSendMessage(text=text), src)
            return

    if isinstance(event.source, SourceUser):
        results = kwd.search_sticker_keyword(sticker_id)
        
        if results is not None:
            kwdata = u'相關回覆組ID: {}。\n'.format(u', '.join([unicode(result[int(kwdict_col.id)]) for result in results]))
        else:
            kwdata = u'無相關回覆組ID。\n'

        api_reply(rep,
                [TextSendMessage(text=kwdata + u'貼圖圖包ID: {}\n貼圖圖片ID: {}'.format(package_id, sticker_id)),
                 TextSendMessage(text=u'圖片路徑(Android):\nemulated\\0\\Android\\data\\jp.naver.line.android\\stickers\\{}\\{}'.format(package_id, sticker_id)),
                 TextSendMessage(text=u'圖片路徑(Windows):\nC:\\Users\\USER_NAME\\AppData\\Local\\LINE\\Data\\Sticker\\{}\\{}'.format(package_id, sticker_id)),
                 TextSendMessage(text=u'圖片路徑(網路):\n{}'.format(kw_dict_mgr.sticker_png_url(sticker_id)))],
                src)
    else:
        auto_reply_system(rep, sticker_id, True, src)


@handler.add(MessageEvent, message=ImageMessage)
def handle_content_message(event):
    msg_track.log_message_activity(line_api_proc.source_channel_id(event.source), msg_event_type.recv_pic)
    
    token = event.reply_token
    msg = event.message
    src = event.source

    try:
        message_content = line_api.get_content(msg.id)

        with tempfile.NamedTemporaryFile(dir=static_tmp_path, prefix='jpg-', delete=False) as tf:
            for chunk in message_content.iter_content():
                tf.write(chunk)
            tempfile_path = tf.name

        dist_path = tempfile_path + '.jpg'
        dist_name = os.path.basename(dist_path)
        os.rename(tempfile_path, dist_path)

        api_reply(token, [TextSendMessage(text='Save content.'), 
                          TextSendMessage(text=request.host_url + os.path.join('static', 'tmp', dist_name))], src)
    except ImgurClientError as e:
        text = u'開機時間: {}\n\n'.format(sys_data.boot_up)
        text += u'Imgur API發生錯誤，狀態碼: {}\n\n錯誤訊息: {}'.format(e.status_code, e.error_message.decode("utf-8"))

        error_msg = webpage_generator.rec_error(text, line_api_proc.source_channel_id(src))
        api_reply(token, TextSendMessage(text=error_msg), src)
    except Exception as exc:
        text = u'開機時間: {}\n\n'.format(sys_data.boot_up)
        exc_type, exc_obj, exc_tb = sys.exc_info()
        text += u'錯誤種類: {}\n\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, exc.message.decode("utf-8"))
        
        error_msg = webpage_generator.rec_error(text, line_api_proc.source_channel_id(src))
        api_reply(token, TextSendMessage(text=error_msg), src)



# Incomplete
@handler.add(PostbackEvent)
def handle_postback(event):
    return
    if event.postback.data == 'ping':
        api_reply(event.reply_token, TextSendMessage(text='pong'), event.source)


# Incomplete
@handler.add(MessageEvent, message=LocationMessage)
def handle_location_message(event):
    msg_track.log_message_activity(line_api_proc.source_channel_id(event.source), msg_event_type.recv_txt)
    return

    api_reply(event.reply_token,
        LocationSendMessage(title=event.message.title, address=event.message.address,
            latitude=event.message.latitude, longitude=event.message.longitude),
        event.source)


# Incomplete
@handler.add(MessageEvent, message=(VideoMessage, AudioMessage))
def handle_content_message(event):
    msg_track.log_message_activity(line_api_proc.source_channel_id(event.source), msg_event_type.recv_txt)
    return

    if isinstance(event.message, ImageMessage):
        ext = 'jpg'
    elif isinstance(event.message, VideoMessage):
        ext = 'mp4'
    elif isinstance(event.message, AudioMessage):
        ext = 'm4a'
    else:
        return

    message_content = api.get_message_content(event.message.id)
    with tempfile.NamedTemporaryFile(dir=static_tmp_path, prefix=ext + '-', delete=False) as tf:
        for chunk in message_content.iter_content():
            tf.write(chunk)
        tempfile_path = tf.name

    dist_path = tempfile_path + '.' + ext
    dist_name = os.path.basename(dist_path)
    os.rename(tempfile_path, dist_path)

    api_reply(event.reply_token, [TextSendMessage(text='Save content.'),
            TextSendMessage(text=request.host_url + os.path.join('static', 'tmp', dist_name))], event.source)


@handler.add(FollowEvent)
def handle_follow(event):
    api_reply(event.reply_token, introduction_template(), event.source)

# Incomplete
@handler.add(UnfollowEvent)
def handle_unfollow():
    return

    app.logger.info("Got Unfollow event")


@handler.add(JoinEvent)
def handle_join(event):
    src = event.source
    reply_token = event.reply_token
    cid = line_api_proc.source_channel_id(src)

    global command_executor

    if not isinstance(event.source, SourceUser):
        group_data = gb.get_group_by_id(cid)
        if group_data is None:
            added = gb.new_data(cid, MAIN_UID, administrator)
            msg_track.new_data(cid)

            api_reply(reply_token, 
                      [TextMessage(text=u'群組資料註冊{}。'.format(u'成功' if added else u'失敗')),
                       introduction_template()], 
                       src)
        else:
            api_reply(reply_token, 
                      [TextMessage(text=u'群組資料已存在。'),
                       TextMessage(text=command_exec.G(src, [None, None, None])),
                       introduction_template()], 
                       cid)


def introduction_template():
    buttons_template = ButtonsTemplate(title=u'機器人簡介', text='歡迎使用小水母！', 
            actions=[URITemplateAction(label=u'點此開啟使用說明', uri='https://sites.google.com/view/jellybot'),
                URITemplateAction(label=u'點此導向開發者LINE帳號', uri='http://line.me/ti/p/~raenonx'),
                MessageTemplateAction(label=u'點此查看群組資料', text='JC\nG')])
    template_message = TemplateSendMessage(alt_text=u'機器人簡介', template=buttons_template)
    return template_message


def api_reply(reply_token, msgs, src):
    if not sys_data.silence:
        if not isinstance(msgs, (list, tuple)):
            msgs = [msgs]

        for msg in msgs:
            if isinstance(msg, TemplateSendMessage):
                msg_track.log_message_activity(line_api_proc.source_channel_id(src), msg_event_type.send_stk)
            elif isinstance(msg, TextSendMessage):
                msg_track.log_message_activity(line_api_proc.source_channel_id(src), msg_event_type.send_txt)

                if len(msg.text) > 2000:
                    api.reply_message(reply_token, 
                                      TextSendMessage(text=error.main.text_length_too_long(webpage_generator.rec_text(msgs))))
                    return

        api.reply_message(reply_token, msgs)
    else:
        print '=================================================================='
        print 'Bot set to silence. Expected message to reply will display below: '
        print msgs
        print '=================================================================='


def intercept_text(event):
    user_id = line_api_proc.source_user_id(event.source)
    user_profile = line_api.profile(user_id)

    print '==========================================='
    print 'From Channel ID \'{}\''.format(line_api_proc.source_channel_id(event.source))
    print 'From User ID \'{}\' ({})'.format(user_id, user_profile.display_name.encode('utf-8') if user_profile is not None else 'unknown')
    print 'Message \'{}\''.format(event.message.text.encode('utf-8'))
    print '=================================================================='


def auto_reply_system(token, keyword, is_sticker_kw, src):
    cid = line_api_proc.source_channel_id(src)

    if gb.is_group_set_to_silence(cid):
        return False

    res = kwd.get_reply(keyword, is_sticker_kw)
    if res is not None:
        msg_track.log_message_activity(line_api_proc.source_channel_id(src), msg_event_type.recv_stk_repl if is_sticker_kw else msg_event_type.recv_txt_repl)
        result = res[0]
        reply_obj = kw_dict_mgr.split_reply(result[int(kwdict_col.reply)].decode('utf-8'))

        if result[int(kwdict_col.is_pic_reply)]:                                                                         
            api_reply(token, TemplateSendMessage(alt_text=u'(圖片/貼圖回覆)\n{}回覆圖片URL: {}\n關鍵字ID: {}'.format(u'' if reply_obj['attachment'] is None else u'{}\n\n'.format(reply_obj['attachment']),
                    reply_obj['main'], 
                    result[int(kwdict_col.id)]),
                template=ButtonsTemplate(text=u'{}ID: {}'.format(u'' if reply_obj['attachment'] is None else u'{}\n\n'.format(reply_obj['attachment']),
                    result[int(kwdict_col.id)]), 
                    thumbnail_image_url=reply_obj['main'],
                    actions=[URITemplateAction(label=u'原始圖片', uri=reply_obj['main'])])), src)
            return True
        else:
            api_reply(token, 
                      TextSendMessage(text=reply_obj['main']),
                      src)
            return True

    return False


def minigame_rps_capturing(rps_obj, is_sticker, content, uid):
    if rps_obj is not None and line_api_proc.is_valid_user_id(uid) and rps_obj.has_player(uid):
        if rps_obj.enabled:
            battle_item = rps_obj.find_battle_item(is_sticker, content)
            if battle_item is not None:
                result = rps_obj.play(battle_item, uid)
                if result is not None:
                    return result
                else:
                    sys_data.game_cmd_dict['RPS'].count += 1
                    if rps_obj.is_waiting_next:
                        return u'等待下一個玩家出拳中...'
                    if rps_obj.result_generated:
                        return rps_obj.result_text()


if __name__ == "__main__":
    # create tmp dir for download content
    make_static_tmp_dir()

    app.run(port=os.environ['PORT'], host='0.0.0.0')

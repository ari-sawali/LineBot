# -*- coding: utf-8 -*-

# TODO: Handle not friend(has uid but no profile)
# TODO: pymongo shell
# TODO: recognize account id(sender_id) instead of password
# TODO: last called pair sequence id

# TODO: USER MANUAL->new line of content has been changed ('\n'->use cmd to trans \n)
# TODO: User Manual -> Priority on pair belongs to group

# TODO: Announcement -> Database migrate, will delete some pair, including all disabled pairs and some inappropriate pair (Thanks 小緯(Anonymous) for reviewing), selection process is anonymous(not targeted)
# TODO: Announcement -> When name changed, bot may be unstable
# TODO: Announcement -> According to free plan, some may not receive personal push notification

# IMPORTANT: Config -> Calculator Timeout, kw_dict duplicate CD

# import custom module
from bot import webpage_auto_gen, game_objects, db_query_manager
from bot.system import line_api_proc, string_can_be_int, system_data, imgur_proc

import msg_handler

import os, sys, errno
import tempfile
import traceback
import validators
import time
from collections import defaultdict
from urlparse import urlparse
from datetime import datetime
from error import error
from flask import Flask, request, url_for
from multiprocessing.pool import ThreadPool

# import for Oxford Dictionary
import httplib
import requests
import json

# Database import
import db

# tool import
import tool

# games import
import game

# import LINE Messaging API
from linebot import (
    LineBotApi, WebhookHandler, exceptions
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage, 
    SourceUser, SourceGroup, SourceRoom,
    TemplateSendMessage, ConfirmTemplate, MessageTemplateAction,
    ButtonsTemplate, URITemplateAction, PostbackTemplateAction,
    CarouselTemplate, CarouselColumn, PostbackEvent,
    StickerMessage, StickerSendMessage, LocationMessage, LocationSendMessage,
    ImageMessage, VideoMessage, AudioMessage,
    UnfollowEvent, FollowEvent, JoinEvent, LeaveEvent, BeaconEvent
)

# import imgur API
from imgur import ImgurClient
from imgur.helpers.error import ImgurClientError

# Main initialization
app = Flask(__name__)
handle_pool = ThreadPool(processes=4)

# Databases initialization
import pymongo
MONGO_DB_URI = os.getenv('MONGO_DB_URI', None)
if MONGO_DB_URI is None:
    print 'Define uri of MongoDB (Complete connection string).'
    sys.exit(1)

group_data = db.group_manager(MONGO_DB_URI)

# TODO: group data usage change (Find all ref)

db_query = db_query_manager("postgres", os.environ["DATABASE_URL"], app)
kwd = db.kw_dict_mgr(db_query)
gb = db.group_ban(db_query)
msg_track = db.message_tracker(db_query)

app_root_url = os.getenv('APP_ROOT_URL', None)
if app_root_url is None or app_root_url.startswith('http'):
    print 'Define App Root URL / Remove HTTP protocol of url'
    sys.exit(1)
else:
    app.config.update(SERVER_NAME=app_root_url)

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
handler = WebhookHandler(channel_secret)
line_api = line_api_proc(LineBotApi(channel_access_token))

# Imgur APi instantiation
imgur_client_id = os.getenv('IMGUR_CLIENT_ID', None)
imgur_client_secret = os.getenv('IMGUR_CLIENT_SECRET', None)
if imgur_client_id is None:
    print('Specify IMGUR_CLIENT_ID environment variable.')
    sys.exit(1)
if imgur_client_secret is None:
    print('Specify IMGUR_CLIENT_SECRET environment variable.')
    sys.exit(1)
imgur_api = imgur_proc(ImgurClient(imgur_client_id, imgur_client_secret))

# currency exchange api
oxr_app_id = os.getenv('OXR_APP_ID', None)
if oxr_app_id is None:
    print 'app id of open exchange (oxr) is not defined in environment variables.'
    sys.exit(1)
oxr_client = tool.curr_exc.oxr(oxr_app_id)

# Oxford Dictionary Environment initialization
oxford_dict_obj = msg_handler.oxford_dict('en')

# File path
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')
    
# Webpage auto generator
webpage_generator = webpage_auto_gen.webpage(app)

# Message handler initialization
command_executor = msg_handler.text_msg(app, line_api, kwd, gb, msg_track, 
                                        oxford_dict_obj, [group_mod, group_admin, administrator], sys_data, 
                                        game_data, webpage_generator, imgur_api)
helper_executor = msg_handler.helper(sys_data)
game_executor = msg_handler.game_msg(game_data, line_api)
img_executor = msg_handler.img_msg(line_api, imgur_api, static_tmp_path, kwd)

# Tool instance initialization
str_calc = tool.txt_calc.text_calculator(20.0)

# function for create tmp dir for download content
def make_tmp_dir():
    try:
        os.makedirs(static_tmp_path)
    except OSError as exc:
        import shutil

        if exc.errno == errno.EEXIST:
            shutil.rmtree(static_tmp_path)
            make_tmp_dir()
        elif os.path.isdir(static_tmp_path):
            raise Exception('Path has been set to represent the static temporary path.')
        else:
            raise

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handle_pool.apply(handler.handle, args=(body, signature))
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

@app.route("/latex/<timestamp>", methods=['GET'])
def latex_webpage(timestamp):
    sys_data.view_webpage()
    latex_script = webpage_generator.get_content(webpage_auto_gen.content_type.LaTeX, timestamp)
    return webpage_auto_gen.webpage.latex_render(latex_script)

@app.route("/ranking/<type>", methods=['GET'])
def full_ranking(type):
    sys_data.view_webpage()
    if type == 'user':
        content = db.kw_dict_mgr.list_user_created_ranking(line_api, kwd.user_created_rank(50))
    elif type == 'used':
        content = db.kw_dict_mgr.list_keyword_ranking(kwd.order_by_usedrank(10000))
    elif type == 'called':
        content = db.kw_dict_mgr.list_keyword_recently_called(kwd.recently_called(10000))
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

    # IMPORTANT: linked keyword (test block)
    if text == 'confirm':
        carousel_template = CarouselTemplate(columns=[
            CarouselColumn(text='Linked 1~3', title='Linked 1~3 (Title)', 
                           actions=[MessageTemplateAction(label='1 (ACTUAL)', text='小水母'),
                                    MessageTemplateAction(label='2', text='LINKED'),
                                    MessageTemplateAction(label='3', text='LINKED')]),
            CarouselColumn(text='Linked 4~6', title='Linked 4~6 (Title)', 
                           actions=[MessageTemplateAction(label='4', text='LINKED'),
                                    MessageTemplateAction(label='5', text='LINKED'),
                                    MessageTemplateAction(label='6', text='LINKED')]),
            CarouselColumn(text='Linked 7~9', title='Linked 7~9 (Title)', 
                           actions=[MessageTemplateAction(label='1', text='LINKED'),
                                    MessageTemplateAction(label='2', text='LINKED'),
                                    MessageTemplateAction(label='3', text='LINKED')]),
            CarouselColumn(text='Linked 10~12', title='Linked 10~12 (Title)', 
                           actions=[MessageTemplateAction(label='1', text='LINKED'),
                                    MessageTemplateAction(label='2', text='LINKED'),
                                    MessageTemplateAction(label='3', text='LINKED')]),
            CarouselColumn(text='Linked 13~15', title='Linked 13~15 (Title)', 
                           actions=[MessageTemplateAction(label='1', text='LINKED'),
                                    MessageTemplateAction(label='2', text='LINKED'),
                                    MessageTemplateAction(label='3', text='LINKED')])])
        template_message = TemplateSendMessage(alt_text='Linked word template (Related ID: 1, 2, 3...15)', template=carousel_template)
        api_reply(event.reply_token, template_message, src)

    try:
        if text == '561563ed706e6f696abbe050ad79cf334b9262da6f83bc1dcf7328f2':
            sys_data.intercept = not sys_data.intercept
            api_reply(token, TextSendMessage(text='Bot {}.'.format('start to intercept messages' if sys_data.intercept else 'stop intercepting messages')), src)
            return
        elif sys_data.intercept:
            intercept_text(event)

        if text == administrator:
            line_api.reply_message(token, TextSendMessage(text='Bot set to {}.'.format('Active' if sys_data.silence else 'Silent')))
            sys_data.silence = not sys_data.silence
            return
        elif sys_data.silence:
            return

        if text == '43afdb2391686dd9710c3879a86c04b5c0a2fc3391ffd2c6a05e4ce0':
            sys_data.calc_debug = not sys_data.calc_debug
            api_reply(token, TextSendMessage(text='Calculator debugging {}.'.format('enabled' if sys_data.calc_debug else 'disabled')), src)
            return

        msg_track.log_message_activity(line_api_proc.source_channel_id(src), db.msg_event_type.recv_txt)

        if text == 'ERRORERRORERRORERROR':
            raise Exception('THIS ERROR IS CREATED FOR TESTING PURPOSE.')
        elif splitter in text:
            head, cmd, oth = msg_handler.split(text, splitter, 3)

            if head == 'JC':
                params = command_executor.split_verify(cmd, splitter, oth)

                if isinstance(params, unicode):
                    api_reply(token, TextSendMessage(text=params), src)
                    return
                else:
                    sys_data.sys_cmd_dict[cmd].count += 1
                
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
                    text = command_executor.P(src, params, oxr_client)

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
                # SHA224 of last PICTURE
                elif cmd == 'PIC':
                    text_tuple = command_executor.PIC(src, params)

                    api_reply(token, [TextSendMessage(text=text) for text in text_tuple], src)
                # TRANSLATE text to URL form
                elif cmd == 'T':
                    text = command_executor.T(src, params)

                    api_reply(token, TextSendMessage(text=text), src)
                # CURRENCY exchange
                elif cmd == 'C':
                    text = command_executor.C(src, params, oxr_client)

                    api_reply(token, TextSendMessage(text=text), src)
                else:
                    sys_data.sys_cmd_dict[cmd].count -= 1
            elif head == 'HELP':
                params = helper_executor.split_verify(cmd, splitter, oth)

                if isinstance(params, unicode):
                    api_reply(token, TextSendMessage(text=params), src)
                    return
                else:
                    sys_data.helper_cmd_dict[cmd].count += 1

                if cmd == 'MFF':
                    message_instance = helper_executor.MFF(params)

                    api_reply(token, message_instance, src)
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
            elif head == 'FX':
                calc_str = cmd + ('' if oth is None else splitter + oth)

                # IMPORTANT: temp, add analysis
                calc_result = str_calc.calculate(calc_str, sys_data.calc_debug, True)
                sys_data.helper_cmd_dict['CALC'].count += 1

                result_str = calc_result.get_basic_text()

                if calc_result.over_length:
                    text = u'因算式結果長度大於100字，為避免洗板，請點選網址察看結果。\n{}'.format(webpage_generator.rec_text(result_str))
                else:
                    text = result_str

                if calc_result.latex_avaliable:
                    text += u'\nLaTeX URL:\n{}'.format(webpage_generator.rec_latex(calc_result.latex))

                api_reply(token, TextSendMessage(text=text), src)

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
                calc_result = str_calc.calculate(text, sys_data.calc_debug)
                if calc_result.success or calc_result.timeout:
                    sys_data.helper_cmd_dict['CALC'].count += 1

                    result_str = calc_result.get_basic_text()

                    if calc_result.over_length:
                        text = u'因算式結果長度大於100字，為避免洗板，請點選網址察看結果。\n{}'.format(webpage_generator.rec_text(result_str))
                    else:
                        text = result_str

                    api_reply(token, TextSendMessage(text=text), src)
                    return
    except exceptions.LineBotApiError as ex:
        text = u'開機時間: {}\n\n'.format(sys_data.boot_up)
        text += u'LINE API發生錯誤，狀態碼: {}\n\n'.format(ex.status_code)
        text += u'錯誤內容: {}'.format(ex.error.as_json_string()) 

        error_msg = webpage_generator.rec_error(text, traceback.format_exc().decode('utf-8'), line_api_proc.source_channel_id(src))
        api_reply(token, TextSendMessage(text=error_msg), src)
    except Exception as exc:
        text = u'開機時間: {}\n\n'.format(sys_data.boot_up)
        exc_type, exc_obj, exc_tb = sys.exc_info()
        text += u'錯誤種類: {}\n\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, exc.message.decode("utf-8"))
        
        error_msg = webpage_generator.rec_error(text, traceback.format_exc().decode('utf-8'), line_api_proc.source_channel_id(src))
        api_reply(token, TextSendMessage(text=error_msg), src)


@handler.add(MessageEvent, message=StickerMessage)
def handle_sticker_message(event):
    package_id = event.message.package_id
    sticker_id = event.message.sticker_id
    rep = event.reply_token
    src = event.source

    try:
        cid = line_api_proc.source_channel_id(src)
    
        sys_data.set_last_sticker(cid, sticker_id)

        global game_data
        rps_obj = game_data.get_rps(cid)

        msg_track.log_message_activity(cid, db.msg_event_type.recv_stk)

        if rps_obj is not None:
            text = minigame_rps_capturing(rps_obj, True, sticker_id, line_api_proc.source_user_id(src))
            if text is not None:
                api_reply(rep, TextSendMessage(text=text), src)
                return

        if isinstance(event.source, SourceUser):
            results = kwd.search_sticker_keyword(sticker_id)
            
            if results is not None:
                kwdata = u'相關回覆組ID: {}。\n'.format(u', '.join([unicode(result[int(db.kwdict_col.id)]) for result in results]))
            else:
                kwdata = u'無相關回覆組ID。\n'

            api_reply(rep, 
                      [TextSendMessage(text=kwdata + u'貼圖圖包ID: {}\n貼圖圖片ID: {}'.format(package_id, sticker_id)),
                      TextSendMessage(text=u'圖片路徑(Android):\nemulated\\0\\Android\\data\\jp.naver.line.android\\stickers\\{}\\{}'.format(package_id, sticker_id)),
                      TextSendMessage(text=u'圖片路徑(Windows):\nC:\\Users\\USER_NAME\\AppData\\Local\\LINE\\Data\\Sticker\\{}\\{}'.format(package_id, sticker_id)),
                      TextSendMessage(text=u'圖片路徑(網路):\n{}'.format(db.kw_dict_mgr.sticker_png_url(sticker_id)))],
                      src)
        else:
            auto_reply_system(rep, sticker_id, True, src)
    except exceptions.LineBotApiError as ex:
        text = u'開機時間: {}\n\n'.format(sys_data.boot_up)
        text += u'LINE API發生錯誤，狀態碼: {}\n\n'.format(ex.status_code)
        for err in ex.error.details:
            text += u'錯誤內容: {}\n錯誤訊息: {}\n'.format(err.property, err.message.decode("utf-8"))

        error_msg = webpage_generator.rec_error(text, traceback.format_exc().decode('utf-8'), line_api_proc.source_channel_id(src))
        api_reply(rep, TextSendMessage(text=error_msg), src)
    except Exception as exc:
        text = u'開機時間: {}\n\n'.format(sys_data.boot_up)
        exc_type, exc_obj, exc_tb = sys.exc_info()
        text += u'錯誤種類: {}\n\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, exc.message.decode("utf-8"))
        
        error_msg = webpage_generator.rec_error(text, traceback.format_exc().decode('utf-8'), line_api_proc.source_channel_id(src))
        api_reply(rep, TextSendMessage(text=error_msg), src)


@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    msg_track.log_message_activity(line_api_proc.source_channel_id(event.source), db.msg_event_type.recv_pic)

    src = event.source
    token = event.reply_token
    msg = event.message

    cid = line_api_proc.source_channel_id(src)
    
    try:
        image_sha = img_executor.image_sha224_of_message(msg)
        sys_data.set_last_pic_sha(cid, image_sha)

        if isinstance(src, SourceUser):
            image_uploaded = img_executor.upload_imgur(msg)

            send_message_list = [TextSendMessage(text=u'檔案雜湊碼(SHA224)'), TextSendMessage(text=image_sha)]
            send_message_list.extend([TextSendMessage(text=txt) for txt in image_uploaded])

            api_reply(token, send_message_list, src)
        else:
            auto_reply_system(token, image_sha, False, src, True)
    except Exception as exc:
        text = u'開機時間: {}\n\n'.format(sys_data.boot_up)
        exc_type, exc_obj, exc_tb = sys.exc_info()
        text += u'錯誤種類: {}\n\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, exc.message.decode("utf-8"))
        
        error_msg = webpage_generator.rec_error(text, traceback.format_exc().decode('utf-8'), line_api_proc.source_channel_id(src))
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
    msg_track.log_message_activity(line_api_proc.source_channel_id(event.source), db.msg_event_type.recv_txt)
    return

    api_reply(event.reply_token,
        LocationSendMessage(title=event.message.title, address=event.message.address,
            latitude=event.message.latitude, longitude=event.message.longitude),
        event.source)


# Incomplete
@handler.add(MessageEvent, message=(VideoMessage, AudioMessage))
def handle_media_message(event):
    msg_track.log_message_activity(line_api_proc.source_channel_id(event.source), db.msg_event_type.recv_txt)
    return

    if isinstance(event.message, ImageMessage):
        ext = 'jpg'
    elif isinstance(event.message, VideoMessage):
        ext = 'mp4'
    elif isinstance(event.message, AudioMessage):
        ext = 'm4a'
    else:
        return

    message_content = line_api.get_content(event.message.id)
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


# TODO: make wrapper class
def api_reply(reply_token, msgs, src):
    if not sys_data.silence:
        if not isinstance(msgs, (list)):
            msgs = [msgs]

        for index, msg in enumerate(msgs):
            if isinstance(msg, TemplateSendMessage):
                msg_track.log_message_activity(line_api_proc.source_channel_id(src), db.msg_event_type.send_stk)
            elif isinstance(msg, TextSendMessage):
                msg_track.log_message_activity(line_api_proc.source_channel_id(src), db.msg_event_type.send_txt)

                if len(msg.text) > 2000:
                    msgs[index] = TextSendMessage(text=error.main.text_length_too_long(webpage_generator.rec_text(msg.text)))

        line_api.reply_message(reply_token, msgs)
    else:
        print '=================================================================='
        print 'Bot set to silence. Expected message to reply will display below: '
        print msgs
        print '=================================================================='


def intercept_text(event):
    src = event.source
    uid = line_api_proc.source_user_id(src)

    user_profile = line_api.profile(uid, src)

    print '==========================================='
    print 'From Channel ID \'{}\''.format(line_api_proc.source_channel_id(src))
    print 'From User ID \'{}\' ({})'.format(uid, 
                                            'unknown' if user_profile is None else (user_profile.display_name.encode('utf-8')
                                            if user_profile.display_name is not None else '(Empty)'))
    print 'Message \'{}\''.format(event.message.text.encode('utf-8'))
    print '=================================================================='


def auto_reply_system(token, keyword, is_sticker_kw, src, is_kw_pic_sha=False):
    cid = line_api_proc.source_channel_id(src)

    if gb.is_group_set_to_silence(cid):
        return False

    res = kwd.get_reply(keyword, is_sticker_kw, is_kw_pic_sha)
    if res is not None:
        msg_track.log_message_activity(line_api_proc.source_channel_id(src), 
                                       db.msg_event_type.recv_stk_repl if is_sticker_kw else db.msg_event_type.recv_txt_repl)
        result = res[0]
        reply_obj = db.kw_dict_mgr.split_reply(result[int(db.kwdict_col.reply)].decode('utf-8'), result[int(db.kwdict_col.is_pic_reply)])

        if result[int(db.kwdict_col.is_pic_reply)]:
            reply_object_list = [ImageSendMessage(original_content_url=reply_obj['main'], preview_image_url=reply_obj['main'])]

            if reply_obj['attachment'] is not None:
                reply_object_list.append(TextSendMessage(text=reply_obj['attachment']))
                
            api_reply(token, reply_object_list, src)
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
    make_tmp_dir()

    app.run(port=os.environ['PORT'], host='0.0.0.0')

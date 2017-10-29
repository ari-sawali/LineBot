# -*- coding: utf-8 -*-

# IMPORTANT: prevent loop (https://stackoverflow.com/questions/4751092/identify-which-iteration-you-are-on-in-a-loop-in-python)
# IMPORTANT: create avtivity point of group(calculate all stats of group)
# IMPORTANT: rank of messages
# IMPORTANT: cache keyword_dict
# IMPORTANT: statistics of sticker 
# IMPORTANT: use mail api to send error report
# IMPORTANT: command to get user permission (P)
# IMPORTANT: set expire time to pair
# TODO: keyword pair global, local ranking
# TODO: hide keyword pair from indexing(Q I)
# TODO: self silent (new db), turn off auto upload
# TODO: message activity tracking
# TODO: self diagnostic
# UNDONE: group_data will save empty mem field in database
# UNDONE: game_msg_handler Shorten + Modulize
# UNDONE: find related pair of sticker (using global keyword dict manager)
# UNDONE: increase performance of handling message (not multi processing)
# UNDONE: increase performance of calling ranking by pair (integrate?)
# UNDONE: increase performance of getting multi user's profile (multi process/thread? - https://docs.python.org/2/library/multiprocessing.html)
# UNDONE: format timezone
# UNDONE: machine learning to filter content - https://machine-learning-python.kspax.io/

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

# import custom module
import bot

# import for Oxford Dictionary
import httplib
import requests
import json

# Database import
import db

# tool import
import tool

# import LINE Messaging API
from linebot import (
    LineBotApi, WebhookHandler, exceptions
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage, 
    TemplateSendMessage, ConfirmTemplate, MessageTemplateAction,
    ButtonsTemplate, URITemplateAction, PostbackTemplateAction,
    CarouselTemplate, CarouselColumn, PostbackEvent,
    StickerMessage, StickerSendMessage, LocationMessage, LocationSendMessage,
    ImageMessage, VideoMessage, AudioMessage, FileMessage, 
    UnfollowEvent, FollowEvent, JoinEvent, LeaveEvent, BeaconEvent
)
from linebot.exceptions import LineBotApiError

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
    print 'Define uri of MongoDB (Complete connection string) in environment variable.'
    sys.exit(1)

app_root_url = os.getenv('APP_ROOT_URL', None)
if app_root_url is None or app_root_url.startswith('http'):
    print 'Define App Root URL / Remove HTTP protocol of url'
    sys.exit(1)
else:
    app.config.update(SERVER_NAME=app_root_url)

# system command related initialization
sys_data = bot.system_data()
cmd_mgr = bot.commands_manager(bot.cmd_dict)

# configurations initialization
config_mgr = bot.config_manager('SystemConfig.ini')
sys_config = db.system_config(MONGO_DB_URI)
    
# Webpage auto generator
webpage_generator = bot.webpage_manager(app, MONGO_DB_URI)

# System initialization
ADMIN_UID = os.getenv('ADMIN_UID', None)
if ADMIN_UID is None:
    print 'Define bot admin uid for creating new group data.'
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
line_api = bot.line_api_wrapper(LineBotApi(channel_access_token), webpage_generator)

# Imgur APi instantiation
imgur_client_id = os.getenv('IMGUR_CLIENT_ID', None)
imgur_client_secret = os.getenv('IMGUR_CLIENT_SECRET', None)
if imgur_client_id is None:
    print('Specify IMGUR_CLIENT_ID environment variable.')
    sys.exit(1)
if imgur_client_secret is None:
    print('Specify IMGUR_CLIENT_SECRET environment variable.')
    sys.exit(1)
imgur_api_wrapper = bot.system.imgur_api_wrapper(ImgurClient(imgur_client_id, imgur_client_secret))

# currency exchange api
oxr_app_id = os.getenv('OXR_APP_ID', None)
if oxr_app_id is None:
    print 'app id of open exchange (oxr) is not defined in environment variables.'
    sys.exit(1)
oxr_client = tool.curr_exc.oxr(oxr_app_id)

# Oxford Dictionary Environment initialization
oxford_dict_obj = bot.oxford_api_wrapper('en')

# File path
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# Tool instance initialization
str_calc = tool.text_calculator(config_mgr.getint(bot.config_category.TIMEOUT, bot.config_category_timeout.CALCULATOR))

# Message handler initialization
text_handler = bot.msg_handler.text_msg_handler(cmd_mgr, app, config_mgr, line_api, MONGO_DB_URI, 
                                               oxford_dict_obj, sys_data, webpage_generator, imgur_api_wrapper, oxr_client, str_calc)
game_handler = bot.msg_handler.game_msg_handler(MONGO_DB_URI, line_api, cmd_mgr)
img_handler = bot.msg_handler.img_msg_handler(line_api, imgur_api_wrapper, static_tmp_path)

global_handler = bot.msg_handler.global_msg_handle(line_api, sys_config, MONGO_DB_URI, text_handler, game_handler, img_handler)

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
        # handler.handle(body, signature)
        handle_pool.apply_async(handler.handle, args=(body, signature))
    except exceptions.InvalidSignatureError:
        abort(400)

    return 'OK'

@app.route("/error", methods=['GET'])
def get_error_list():
    return webpage_generator.html_render_error_list(sys_data.boot_up, webpage_generator.get_error_dict())

@app.route("/webpage/<seq_id>", methods=['GET'])
def get_webpage(seq_id):
    webpage_data = webpage_generator.get_webpage_data(seq_id)
    return bot.webpage_manager.render_webpage(webpage_data)

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    token = event.reply_token
    src = event.source

    try:
        global_handler.handle_text(event)
    except Exception as ex:
        error_msg = u'開機時間: {}\n'.format(sys_data.boot_up)
        if isinstance(ex, LineBotApiError):
            error_msg += u'LINE API發生錯誤，狀態碼: {}\n\n'.format(ex.status_code)
            error_msg += u'錯誤內容: {}\n'.format(ex.error.as_json_string()) 
            if ex.status_code == 429:
                return
        else:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            try:
                error_msg += u'錯誤種類: {}\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, ex.message)
            except UnicodeEncodeError:
                error_msg += u'錯誤種類: {}\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, ex.message.encode("utf-8"))
            except UnicodeDecodeError:
                error_msg += u'錯誤種類: {}\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, ex.message.decode("utf-8"))
        
        try:
            tb_text = traceback.format_exc().decode('utf-8')
        except UnicodeEncodeError:
            tb_text = traceback.format_exc().encode('utf-8')
        except UnicodeDecodeError:
            tb_text = traceback.format_exc()
        error_msg += webpage_generator.rec_error(ex, tb_text, bot.line_api_wrapper.source_channel_id(src), error_msg)

        if sys_config.get(db.config_data.REPLY_ERROR):
            line_api.reply_message_text(token, error_msg)


@handler.add(MessageEvent, message=StickerMessage)
def handle_sticker_message(event):
    token = event.reply_token
    src = event.source

    try:
        global_handler.handle_sticker(event)
    except Exception as ex:
        error_msg = u'開機時間: {}\n'.format(sys_data.boot_up)
        if isinstance(ex, LineBotApiError):
            error_msg += u'LINE API發生錯誤，狀態碼: {}\n\n'.format(ex.status_code)
            error_msg += u'錯誤內容: {}\n'.format(ex.error.as_json_string()) 
            if ex.status_code == 429:
                return
        else:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            try:
                error_msg += u'錯誤種類: {}\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, ex.message)
            except UnicodeEncodeError:
                error_msg += u'錯誤種類: {}\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, ex.message.encode("utf-8"))
            except UnicodeDecodeError:
                error_msg += u'錯誤種類: {}\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, ex.message.decode("utf-8"))
        
        try:
            tb_text = traceback.format_exc().decode('utf-8')
        except UnicodeEncodeError:
            tb_text = traceback.format_exc().encode('utf-8')
        except UnicodeDecodeError:
            tb_text = traceback.format_exc()
        error_msg += webpage_generator.rec_error(ex, tb_text, bot.line_api_wrapper.source_channel_id(src), error_msg)

        if sys_config.get(db.config_data.REPLY_ERROR):
            line_api.reply_message_text(token, error_msg)


@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    src = event.source
    token = event.reply_token

    try:
        global_handler.handle_image(event)
    except Exception as ex:
        error_msg = u'開機時間: {}\n'.format(sys_data.boot_up)
        if isinstance(ex, LineBotApiError):
            error_msg += u'LINE API發生錯誤，狀態碼: {}\n\n'.format(ex.status_code)
            error_msg += u'錯誤內容: {}\n'.format(ex.error.as_json_string()) 
            if ex.status_code == 429:
                return
        else:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            try:
                error_msg += u'錯誤種類: {}\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, ex.message)
            except UnicodeEncodeError:
                error_msg += u'錯誤種類: {}\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, ex.message.encode("utf-8"))
            except UnicodeDecodeError:
                error_msg += u'錯誤種類: {}\n第{}行 - {}'.format(exc_type, exc_tb.tb_lineno, ex.message.decode("utf-8"))
        
        try:
            tb_text = traceback.format_exc().decode('utf-8')
        except UnicodeEncodeError:
            tb_text = traceback.format_exc().encode('utf-8')
        except UnicodeDecodeError:
            tb_text = traceback.format_exc()
        error_msg += webpage_generator.rec_error(ex, tb_text, bot.line_api_wrapper.source_channel_id(src), error_msg)

        if sys_config.get(db.config_data.REPLY_ERROR):
            line_api.reply_message_text(token, error_msg)


@handler.add(FollowEvent)
def handle_follow(event):
    line_api.reply_message(event.reply_token, bot.line_api_wrapper.introduction_template())


@handler.add(JoinEvent)
def handle_join(event):
    reply_token = event.reply_token
    cid = bot.line_api_wrapper.source_channel_id(event.source)
    
    if not bot.line_event_source_type.determine(event.source) == bot.line_event_source_type.USER:
        group_data = db.group_manager(MONGO_DB_URI).get_group_by_id(cid)
        group_action_dict = { '點此查看群組資料': bot.msg_handler.text_msg_handler.HEAD + bot.msg_handler.text_msg_handler.SPLITTER + 'G' }

        template_alt_text = u'群組資料查閱快捷樣板'
        template_title = u'相關指令'

        if group_data is None:
            activation_token = global_handler._group_manager.new_data(cid, db.config_type.ALL)
            
            group_action_dict['啟用公用資料庫'] = bot.msg_handler.text_msg_handler.HEAD + bot.msg_handler.text_msg_handler.SPLITTER + 'GA' + bot.msg_handler.text_msg_handler.SPLITTER + 'ACTIVATE' + bot.msg_handler.text_msg_handler.SPLITTER + activation_token
            group_template = bot.line_api_wrapper.wrap_template_with_action(group_action_dict, template_alt_text, template_title)
            line_api.reply_message(reply_token, 
                                   [bot.line_api_wrapper.introduction_template(),
                                    bot.line_api_wrapper.wrap_text_message(u'群組資料註冊{}。'.format(u'成功' if activation_token is not None else u'失敗'), webpage_generator),
                                    group_template])
        else:
            group_template = bot.line_api_wrapper.wrap_template_with_action(group_action_dict, template_alt_text, template_title)
            line_api.reply_message(reply_token, 
                                   [bot.line_api_wrapper.introduction_template(),
                                    bot.line_api_wrapper.wrap_text_message(u'群組資料已存在。', webpage_generator),
                                    group_template])


# Not Using
@handler.add(PostbackEvent)
def handle_postback(event):
    return

# Not Using
@handler.add(MessageEvent, message=LocationMessage)
def handle_location_message(event):
    text_handler._group_manager.log_message_activity(cid, db.msg_type.LOCATION)

# Not Using
@handler.add(MessageEvent, message=VideoMessage)
def handle_media_message(event):
    text_handler._group_manager.log_message_activity(cid, db.msg_type.VIDEO)
    
# Not Using
@handler.add(MessageEvent, message=AudioMessage)
def handle_media_message(event):
    text_handler._group_manager.log_message_activity(cid, db.msg_type.AUDIO)
    
# Not Using
@handler.add(MessageEvent, message=FileMessage)
def handle_media_message(event):
    text_handler._group_manager.log_message_activity(cid, db.msg_type.FILE)

# Not Using
@handler.add(UnfollowEvent)
def handle_unfollow():
    return


if __name__ == "__main__":
    # create tmp dir for download content
    make_tmp_dir()

    app.run(port=os.environ['PORT'], host='0.0.0.0')

import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio

# Botの設定
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# yt-dlpオプション
youtube_dl.utils.bug_reports_message = lambda: ""
ytdl_format_options = {
    "format": "bestaudio/best",
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "192",
    }],
    # "noplaylist": True,  # プレイリストをスキップ
    # "nocheckcertificate": True,  # SSLエラーを無視
}
ffmpeg_options = {
    # "executable": "ffmpeg-2024-12-16-git-d2096679d5-full_build\\bin\\ffmpeg.exe",
    "options": "-vn",
}
ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

# 再生用クラス
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.3):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Unknown Title")
        self.url = data.get("webpage_url", "")
        self.stream_url = data["url"]  # ストリーミングURL

    @classmethod
    async def from_url(cls, url, *, loop=None, volume=0.3):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        if "entries" in data:  # プレイリストの場合
            data = data["entries"][0]
        filename = data["url"]  # 一時ストリーミングURL
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data, volume=volume)

    async def refresh_stream_url(self):
        """ストリーミングURLを再取得"""
        data = await asyncio.get_event_loop().run_in_executor(None, lambda: ytdl.extract_info(self.url, download=False))
        self.stream_url = data["url"]

# グローバル変数としてキューを管理
music_queue = []
loop_flag = False
current_song = None

def play_next(ctx):
    global current_song, loop_flag

    async def retry_play():
        """ストリーミングURLを再取得して再生"""
        try:
            await current_song.refresh_stream_url()  # ストリームURLを更新
            source = discord.FFmpegPCMAudio(current_song.stream_url, **ffmpeg_options)
            transformed_source = discord.PCMVolumeTransformer(source, volume=current_song.volume)  # 音量を再設定
            ctx.voice_client.play(
                transformed_source,
                after=lambda e: play_next(ctx)
            )
            asyncio.run_coroutine_threadsafe(ctx.send(f"再試行: {current_song.title}"), bot.loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(ctx.send(f"再試行に失敗しました: {e}"), bot.loop)

    if loop_flag and current_song:
        # ループ再生の場合
        source = discord.FFmpegPCMAudio(current_song.stream_url, **ffmpeg_options)
        transformed_source = discord.PCMVolumeTransformer(source, volume=current_song.volume)  # 音量を再設定
        ctx.voice_client.play(
            transformed_source,
            after=lambda e: play_next(ctx)
        )
        asyncio.run_coroutine_threadsafe(ctx.send(f"ループ再生中: {current_song.title}"), bot.loop)
    elif music_queue:
        # 次の曲を再生
        next_song = music_queue.pop(0)
        current_song = next_song
        source = discord.FFmpegPCMAudio(next_song.stream_url, **ffmpeg_options)
        transformed_source = discord.PCMVolumeTransformer(source, volume=next_song.volume)  # 音量を再設定
        ctx.voice_client.play(
            transformed_source,
            after=lambda e: play_next(ctx)
        )
        asyncio.run_coroutine_threadsafe(ctx.send(f"再生中: {next_song.title}"), bot.loop)
    else:
        # キューが空の場合
        current_song = None
        asyncio.run_coroutine_threadsafe(ctx.send("再生が終了しました。"), bot.loop)


# オンライン状態変更コマンド
@bot.command()
async def status(ctx, state: str):
    """Botのオンライン状態を変更"""
    states = {
        "online": discord.Status.online,  # オンライン
        "idle": discord.Status.idle,  # 離席中
        "dnd": discord.Status.dnd,  # 取り込み中
        "invisible": discord.Status.invisible  # オフライン
    }

    if state.lower() in states:
        await bot.change_presence(status=states[state.lower()])
        await ctx.send(f"Botの状態を `{state}` に変更しました。")
    else:
        await ctx.send("無効な状態です。利用可能な状態は: `online`, `idle`, `dnd`, `invisible` です。")

# メインコマンド
# ログイン時(ターミナルに表示)
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # 接続されているボイスチャンネルを確認
    for guild in bot.guilds:
        if guild.voice_client:  # Botがボイスチャンネルに接続している場合
            await guild.voice_client.disconnect()
            print(f"Disconnected from voice channel in guild: {guild.name}")

async def on_error(event, *args, **kwargs):
    with open("error.log", "a") as f:
        f.write(f"Unhandled error: {event}\n")
        f.write(f"Args: {args}\n")
        f.write(f"Kwargs: {kwargs}\n")

async def on_message(message):
    # Bot自身のメッセージは無視
    if message.author == bot.user:
        return

    # メンションされているか確認
    if bot.user in message.mentions:
        await message.channel.send("誰だお前？")

    # コマンド処理を続行
    await bot.process_commands(message)

async def on_error(event, *args, **kwargs):
    with open("error.log", "a") as f:
        f.write(f"Unhandled error: {event}\nArgs: {args}\nKwargs: {kwargs}\n")
    if "voice_client" in kwargs and kwargs["voice_client"].is_connected():
        await asyncio.sleep(5)  # 5秒待機後に再試行
        await kwargs["voice_client"].disconnect()  # 再接続を試みる

# help
@bot.command()
async def help(ctx):
    """利用可能なコマンド一覧を表示"""
    commands_list = [
        "`!join` - ボイスチャンネルに参加します。",
        "`!leave` - ボイスチャンネルから退出します。",
        "`!play [URL]` - 指定したYouTube URLの曲を再生します。",
        "`!pause` - 再生中の音楽を一時停止します。",
        "`!resume` - 一時停止した音楽を再開します。",
        "`!skip` - 現在の曲をスキップします。",
        "`!queue` - 再生待ちのキューを表示します。",
        "`!loop` - 現在の曲をループする/ループを停止します。",
        "`!volume [0-100]` - 音量を調整します。",
        "`!status [online/idle/dnd/invisible]` - Botの状態を変更します。",
        "`!help` - 利用可能なコマンド一覧を表示します。",
    ]
    embed = discord.Embed(
        title="めーちゃん 💜 botのコマンド一覧",
        description="\n".join(commands_list),
        color=discord.Color.blue(),
    )
    await ctx.send(embed=embed)

# join
@bot.command()
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        try:
            # ボイスチャンネルに接続
            await channel.connect()
            await ctx.send(f"{channel.name} に接続しました！")
        except discord.ClientException as e:
            await ctx.send(f"接続エラー: {e}。再試行します...")
            await asyncio.sleep(3)  # 再試行のため少し待機
            try:
                await channel.connect()
                await ctx.send(f"再試行に成功しました！")
            except Exception as retry_error:
                await ctx.send(f"再試行にも失敗しました: {retry_error}")
        except Exception as e:
            await ctx.send(f"予期しないエラーが発生しました: {e}")
    else:
        await ctx.send("ボイスチャンネルに参加してください。")

@bot.command()
async def play(ctx, url):
    """YouTubeの動画またはプレイリストを再生"""
    global current_song

    if not ctx.voice_client:
        await ctx.send("まずボイスチャンネルにBotを参加させてください。")
        return

    try:
        # 動画またはプレイリストの情報を取得
        data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

        if "entries" in data:  # プレイリストの場合
            entries = data["entries"]
            for entry in entries:
                song = await YTDLSource.from_url(entry["webpage_url"], loop=bot.loop)
                music_queue.append(song)
                await ctx.send(f"キューに追加: {song.title}")
            await ctx.send(f"プレイリスト「{data['title']}」をキューに追加しました。")

            # 再生中でない場合、次の曲を再生
            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                play_next(ctx)
        else:  # 単一動画の場合
            song = await YTDLSource.from_url(url, loop=bot.loop)
            if not ctx.voice_client.is_playing():
                current_song = song
                ctx.voice_client.play(song, after=lambda e: play_next(ctx))
                await ctx.send(f"再生中: {song.title}")
            else:
                music_queue.append(song)
                await ctx.send(f"キューに追加: {song.title}")

    except Exception as e:
        await ctx.send(f"再生に失敗しました: {e}")

@bot.command()
async def loop(ctx):
    """現在の曲をループする/停止する"""
    global loop_flag

    if loop_flag:
        loop_flag = False
        await ctx.send("ループを無効にしました。")
    else:
        loop_flag = True
        await ctx.send("現在の曲をループするよう設定しました。")

@bot.command()
async def skip(ctx):
    """現在の曲をスキップ"""
    global loop_flag

    if ctx.voice_client and ctx.voice_client.is_playing():
        loop_flag = False  # スキップ時はループを無効化
        ctx.voice_client.stop()
        await ctx.send("現在の曲をスキップしました。")
    else:
        await ctx.send("スキップする曲がありません。")

@bot.command()
async def queue(ctx):
    """現在のキューを表示"""
    if music_queue:
        queue_list = "\n".join([f"{i+1}. {song.title}" for i, song in enumerate(music_queue)])
        await ctx.send(f"再生待ちのキュー:\n{queue_list}")
    else:
        await ctx.send("キューに曲はありません。")

# pause
@bot.command()
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("再生を一時停止しました。")
    else:
        await ctx.send("再生中の音楽がありません。")

# resume
@bot.command()
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("再生を再開しました。")
    else:
        await ctx.send("音楽は一時停止されていません。")

# volume
@bot.command()
async def volume(ctx, level: int):
    if not (0 <= level <= 100):
        await ctx.send("音量は0から100の間で指定してください。")
        return

    if ctx.voice_client and ctx.voice_client.source:
        ctx.voice_client.source.volume = level / 100  # 音量を調整
        await ctx.send(f"音量を {level}% に設定しました。")
    else:
        await ctx.send("音楽が再生されていません。")

# leave
@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        channel = ctx.author.voice.channel
        try:
            if ctx.voice_client is not None:
                await ctx.voice_client.disconnect()
            await ctx.send(f"ボイスチャンネル {channel.name} から退出しました！")                
        except Exception as e:
            await ctx.send(f"エラーが発生しました: {e}")
    else:
        await ctx.send("Botはボイスチャンネルにいません。")

# Botトークンを入力
bot.run("MTMxODIwMzM0Mjk4NzcyNjk4OA.GJ316E.igG2Y8NRj_0t9og42paDesyfhLB3PGnmiVtqDo")
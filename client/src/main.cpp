// S2S and voice changer
#include <M5Unified.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <M5GFX.h>
#include <FastLED.h>
#include <deque>

# define EXT_BUTTON_PIN 8
# define DATA_PIN 9

m5::Button_Class unit_button;
CRGB LED[1];

// 自宅
// const char* ssid = "SPWH_L13_9DA777"; // Wi-Fi:SSID
// const char* password = "7sH36wT6"; // Wi-Fi:password
// const char* websocket_host = "192.168.0.194"; // WebSocketサーバー:IPアドレス
// const uint16_t websocket_port = 8000; // WebSocketサーバー:ポート番号

// 大学
const char* ssid = "KodamaLabA"; // Wi-Fi:SSID
const char* password = "mediaKart"; // Wi-Fi:password
// const char* ssid = "なりはろいど"; // Wi-Fi:SSID
// const char* password = "9746ea1bce7e"; // Wi-Fi:password
const char* websocket_host = "192.168.10.10"; // WebSocketサーバー:IPアドレス
const uint16_t websocket_port = 8000; // WebSocketサーバー:ポート番号

WebSocketsClient webSocket;
bool is_connected = false; // WebSocketサーバーに接続/非接続

// サーバーから送られてくる1文ごとのWAVデータ(PCM)を格納するキュー
std::deque<std::vector<uint8_t>> audioQueue;
std::vector<uint8_t> receivingBuffer; // 現在受信中のパケット組み立て用
std::vector<uint8_t> playingBuffer;   // 現在再生中のバッファ（メモリ保護用）

std::vector<uint8_t> wavSendBuffer; 
static int16_t *linear_audio_buf;

// 状態管理
enum DeviceState {
  WAITING,    // 待機中
  WAITING_FOR_SHAKE, // チュートリアル開始の振動待ち
  RECORDED, // 録音完了直後
  REQUESTING, // サーバーにリクエスト送信済
  RECEIVING_ACK, // 相槌受信中
  PLAYING_ACK, // 相槌再生中
  RECEIVING_STREAM, // 受信中(ストリーミング)
  PLAYING_STREAM // 再生中(ストリーミング)
};
DeviceState curState = WAITING;

// サーバーからの全データ受信完了フラグ
bool is_response_completed = false;

// 録音設定
bool is_recording = false;

static constexpr const size_t record_number     = 768; // 録音データを格納するバッファのブロック数(理論的には3750=75秒相当まで拡張可能)
static constexpr const size_t record_length     = 320; // 1ブロックあたりのデータ長
static constexpr const size_t record_size       = record_number * record_length; // 全体のバッファサイズ(768 * 320 = 245,760 サンプル)
static constexpr const size_t record_samplerate = 16000; // サンプリングレート

static size_t rec_record_idx  = 2;
static int16_t *rec_data; // 「録音音声データを格納するバッファ」へのポインタ

size_t recording_start_idx = 0; // 録音を開始したブロックのインデックス
size_t num_recorded_blocks = 0; // 録音したブロック数

int speaker_volume = 50;
int battery_alert_level = 10;
bool is_battery_check = false;

const int MAX_VOLUME = 255;
const int MIN_VOLUME = 0;
const int VOL_STEP = 20;

// 画面に状態を表示する関数
void updateDisplay(const char* message) {
    M5.Display.fillScreen(BLACK);
    M5.Display.setCursor(0, 0);
    M5.Display.println(message);
    Serial.println(message);
}

void showBattery(){
    int x = M5.Display.getCursorX();
    int y = M5.Display.getCursorY();
    M5.Display.setCursor(0, 210);
    M5.Display.setTextSize(2);
    M5.Display.printf("%d %%", M5.Power.getBatteryLevel());
    M5.Display.setCursor(x, y);
    M5.Display.setTextSize(1);
}

// WebSocketイベントが発生したときに呼び出される
void webSocketEvent(WStype_t type, uint8_t *payload, size_t length) {
    Serial.printf("[WebSocket] event type: %d\n", type);

    switch(type) {
        case WStype_DISCONNECTED: 
            Serial.printf("[WebSocket] Disconnected!\n");
            is_connected = false;
            receivingBuffer.clear();
            audioQueue.clear();
            curState = WAITING;
            break;
        case WStype_CONNECTED: 
            M5.Display.printf("Connected! URL: %s\n", payload);
            is_connected = true;
            updateDisplay("Please press the button.");
            break;
        case WStype_TEXT: 
            Serial.printf("[WebSocket] Text: %s\n", payload);
            if (strcmp((char*)payload, "MODE_TUTORIAL") == 0) { 
                curState = WAITING_FOR_SHAKE;
                updateDisplay("Tutorial Mode.\nShake me!");
            } else if (strcmp((char*)payload, "MODE_NORMAL") == 0) { 
                curState = WAITING;
                updateDisplay("Normal Mode.\nPress button.");
            } else if(strcmp((char*)payload, "{\"status\": \"received\"}") == 0) {
                // nop
            } else if (strcmp((char*)payload, "VOL_UP") == 0) {
                speaker_volume += VOL_STEP;
                if (speaker_volume > MAX_VOLUME) speaker_volume = MAX_VOLUME;
                M5.Speaker.setVolume(speaker_volume); // 音量アップ
                updateDisplay(("Volume Up: " + String(speaker_volume)).c_str());
            } else if (strcmp((char*)payload, "VOL_DOWN") == 0) {
                speaker_volume -= VOL_STEP;
                if (speaker_volume < MIN_VOLUME) speaker_volume = MIN_VOLUME;
                M5.Speaker.setVolume(speaker_volume); // 音量ダウン
                updateDisplay(("Volume Down: " + String(speaker_volume)).c_str());

            } else if (strcmp((char*)payload, "START_OF_ACK") == 0) { 
                if (curState == REQUESTING) { 
                    receivingBuffer.clear(); 
                    curState = RECEIVING_ACK;
                    M5.Display.println("Receiving ack...");
                }
            } else if (strcmp((char*)payload, "END_OF_ACK") == 0) { 
                if (curState == RECEIVING_ACK && !receivingBuffer.empty()) {
                    M5.Speaker.begin();
                    M5.Speaker.setVolume(speaker_volume);
                    curState = PLAYING_ACK;
                    M5.Display.println("Playing ack...");
                    // 相槌は即再生
                    M5.Speaker.playRaw((const int16_t*)receivingBuffer.data(), receivingBuffer.size() / 2, 44100, false, 1);
                } else {
                    curState = REQUESTING; 
                }
            } 
            // ★変更: ストリーミング音声の開始合図
            else if (strcmp((char*)payload, "START_OF_AUDIO") == 0) { 
                receivingBuffer.clear(); 
                // まだRECEIVING_STREAMでなければ遷移
                if (curState != RECEIVING_STREAM && curState != PLAYING_STREAM) {
                    curState = RECEIVING_STREAM;
                    is_response_completed = false; // フラグリセット
                    M5.Display.println("Receiving stream...");
                }
            } 
            // ★変更: 1文の終了合図 -> キューへ格納
            else if (strcmp((char*)payload, "END_OF_AUDIO") == 0) { 
                if (!receivingBuffer.empty()) {
                    Serial.printf("Pushing sentence to queue. Size: %d\n", receivingBuffer.size());
                    audioQueue.push_back(receivingBuffer); // キューに追加
                    receivingBuffer.clear();
                    
                    // すでに再生中でなければ、PLAYING_STREAM状態へ移行して再生開始を促す
                    if (curState == RECEIVING_STREAM) {
                        curState = PLAYING_STREAM;
                    }
                }
            }
            // ★追加: 全応答終了の合図
            else if (strcmp((char*)payload, "END_OF_RESPONSE") == 0) {
                Serial.println("End of response signal received.");
                is_response_completed = true;
            }
            break;

        case WStype_BIN:
            // 相槌 or ストリーミング音声の受信
            if (curState == RECEIVING_ACK || curState == RECEIVING_STREAM || curState == PLAYING_STREAM) { 
                receivingBuffer.insert(receivingBuffer.end(), payload, payload + length);
            }
            break;
        case WStype_ERROR:
            curState = WAITING;
            updateDisplay("WebSocket Error.");
            break;
        default:
        break;
    }
}

// wavファイルのヘッダ情報
struct WavHeader {
    char riff_header[4] = {'R', 'I', 'F', 'F'};
    uint32_t wav_size; // ファイル全体のサイズ - 8(riff_header+wav_size)
    char wave_header[4] = {'W', 'A', 'V', 'E'};
    char fmt_header[4] = {'f', 'm', 't', ' '};
    uint32_t fmt_chunk_size = 16; // このフィールド雨以降のfmtチャンクのサイズ(2, 1, 1, 2, 2, 1, 1, 4, 2)
    uint16_t audio_format = 1; // PCM
    uint16_t num_channels = 1; // モノラル
    uint32_t sample_rate;
    uint32_t byte_rate; // 1sあたりのバイト数
    uint16_t block_align; // 1サンプルあたりのバイト数(全チャンネル)
    uint16_t bits_per_sample = 16; // 1サンプルあたりの"ビット"数
    char data_header[4] = {'d', 'a', 't', 'a'};
    uint32_t data_size; // 音声データのバイト数
};

// 生の音声データを再生可能なwav形式に変換
bool createWavData(std::vector<uint8_t>& wav_buffer, const int16_t* audio_data, size_t audio_size){
    wav_buffer.clear();

    // 1. 引数で受け取った音声データをもとに、ヘッダの各パラメータを設定
    WavHeader header;
    header.sample_rate = record_samplerate;
    header.data_size = audio_size;
    header.wav_size = audio_size + 36; // wavヘッダ44バイトからriff_headerとwav_size計8バイトを除くと36バイト
    uint32_t bytes_per_sample = header.bits_per_sample / 8; // 1サンプルあたりのバイト数
    header.byte_rate = header.sample_rate * header.num_channels * bytes_per_sample; // 1sあたりのバイト数
    header.block_align = header.num_channels * bytes_per_sample; // 1サンプルあたりのバイト数(全チャンネル)

    // 2. ヘッダと音声データを合わせたWAVファイル全体のサイズ分のメモリを動的確保
    size_t total_size = sizeof(WavHeader) + audio_size;
    wav_buffer.resize(total_size);

    if (wav_buffer.size() != total_size) {
        Serial.println("Failed to allocate memory for WAV data!");
        return false; // メモリ確保失敗
    }

    // 3. 新しいメモリ領域にヘッダと音声データをコピーする
    // ヘッダを先頭にコピー
    memcpy(wav_buffer.data(), &header, sizeof(WavHeader));
    // ヘッダの直後(sizeof(WavHeader)バイトずらした位置)に音声データをコピー
    memcpy(wav_buffer.data() + sizeof(WavHeader), audio_data, audio_size);


    return true;
}

void setup() {
    auto cfg = M5.config();
    M5.begin(cfg);
    M5.Imu.begin();

    Serial.begin(115200);
    showBattery();

    pinMode(EXT_BUTTON_PIN, INPUT_PULLUP);
    FastLED.addLeds<SK6812, DATA_PIN, GRB>(LED, 1);
    LED[0] = CRGB::Black;
    FastLED.setBrightness(0);
    FastLED.show();

    M5.Lcd.setTextFont(&fonts::efontJA_16);
    M5.Display.setTextSize(1);

    wavSendBuffer.reserve(sizeof(WavHeader) + record_size * sizeof(int16_t));
    receivingBuffer.reserve(50000); // サーバーからの音声データ用に50KBを事前確保

    // Wi-Fiへの接続
    M5.Display.printf("Connecting Wi-Fi: %s\n", ssid);
    WiFi.begin(ssid, password);
    while(WiFi.status() != WL_CONNECTED) {
        delay(500);
        M5.Display.printf(".");
    }
    M5.Display.printf("\nWi-Fi connection successful!\n");
    M5.Display.printf("IP: %s\n", WiFi.localIP().toString().c_str());

    WiFi.setSleep(false);

    // WebSocketサーバーに接続
    webSocket.begin(websocket_host, websocket_port, "/ws");

    // 5秒ごとにPingメッセージを自動送信する設定
    // webSocket.setExtraHeaders(); 
    // webSocket.enableHeartbeat(5000, 3000, 2); 

    // イベントハンドラの登録
    webSocket.onEvent(webSocketEvent);

    // マイクから音声データを受け取るためのバッファ領域を確保(SPIRAM)
    rec_data = (typeof(rec_data))heap_caps_malloc(record_size * sizeof(int16_t), MALLOC_CAP_SPIRAM);
    if (rec_data == nullptr) {
        M5.Display.println("Failed to allocate memory for rec_data!");
        return;
    }
    memset(rec_data, 0, record_size * sizeof(int16_t));

    // 録音データを一時格納するためのバッファ領域を確保(SPIRAM)
    linear_audio_buf = (typeof(linear_audio_buf))heap_caps_malloc(record_size * sizeof(int16_t), MALLOC_CAP_SPIRAM);
    if (linear_audio_buf == nullptr) {
        M5.Display.println("Failed to allocate memory for linear_audio_buf!");
        return;
    }
    memset(linear_audio_buf, 0, record_size * sizeof(int16_t));
}

void loop() {
    webSocket.loop();
    M5.update();

    showBattery();

    unit_button.setRawState(millis(), !digitalRead(EXT_BUTTON_PIN));
    

    switch(curState) {
        case WAITING_FOR_SHAKE:
        {
            float ax, ay, az;
            M5.Imu.getAccel(&ax, &ay, &az);
            // 重力加速度(1.0G)との差分で動きを検知
            float accel_mag = sqrt(ax*ax + ay*ay + az*az);
            
            // 閾値(1.5G程度)を超えたらシェイクとみなす
            if (abs(accel_mag - 1.0) > 0.3) { 
                M5.Display.println("Shake detected!");
                // "SHAKE" という文字列を送信
                webSocket.sendBIN((uint8_t *)"SHAKE", 5);
                
                // 一度送ったら通常の待機状態へ
                curState = WAITING;
                updateDisplay("Sent trigger.\nWaiting for voice...");
                delay(1000); // 連続検知防止
            }
            break;
        }

        case WAITING:
            if (is_connected && !M5.Power.isCharging() && !is_battery_check && M5.Power.getBatteryLevel() < battery_alert_level + 1) { // バッテリー残量が10%以下の場合
                int level = M5.Power.getBatteryLevel();
                String strLevel = String(level); // 数値を文字列に変換
                webSocket.sendBIN((uint8_t *)strLevel.c_str(), strLevel.length()); // 文字列をバイト列として送信(c_str()で文字配列のポインタを取得、length()で長さを指定)
                curState = REQUESTING;
                is_battery_check = true;
                break;
            }

            // ボタンが押された瞬間に録音開始
            if (unit_button.wasPressed()) {
                if(!is_recording) { 
                    M5.Display.println("Button is pressed! Recording...");
                    M5.Mic.begin();
                    is_recording = true;
                    recording_start_idx = rec_record_idx; // 録音開始位置を記録
                    num_recorded_blocks = 0;
                }
            } 
            // ボタンが離された瞬間に録音停止
            else if (unit_button.wasReleased()) {
                if(is_recording) {
                    M5.Display.println("Button is released! Stopping...");
                    M5.Mic.end();
                    is_recording = false;
                    M5.Display.println("End recording!");
                    curState = RECORDED;
                }
            }

            // 録音中の処理
            if (is_recording) {
                auto data = &rec_data[rec_record_idx * record_length];
                if (M5.Mic.record(data, record_length, record_samplerate)) {
                    if (++rec_record_idx >= record_number) {
                        rec_record_idx = 0;
                    }
                    
                    if(num_recorded_blocks < record_number) {
                        num_recorded_blocks++;
                    } else {
                         // バッファが満杯になったら自動的に録音を停止
                         M5.Display.println("Buffer full, stopping.");
                         M5.Mic.end();
                         is_recording = false;
                         curState = RECORDED;
                    }
                }
            }
            break;

        case RECORDED: // 録音完了直後
            if(is_connected) {
                is_battery_check = false;

                if(num_recorded_blocks == 0) {
                    curState = WAITING;
                    break;
                }

                // 実際に録音したバイト数を計算
                size_t recorded_samples = num_recorded_blocks * record_length;
                size_t recorded_audio_bytes = recorded_samples * sizeof(int16_t);

                // 音声データをリングバッファからリニアバッファにコピー
                size_t current_idx = recording_start_idx;
                for (size_t i = 0; i < num_recorded_blocks; ++i) {
                    memcpy(&linear_audio_buf[i * record_length], &rec_data[current_idx * record_length], record_length * sizeof(int16_t));
                    if (++current_idx >= record_number) {
                        current_idx = 0;
                    }
                }

                bool wav_success = createWavData(wavSendBuffer, linear_audio_buf, recorded_audio_bytes);

                // WAVファイルを作成
                if (wav_success) {
                    M5.Display.printf("WAV created! Size: %d bytes\n", wavSendBuffer.size());

                    if (is_connected) {
                        webSocket.sendBIN(wavSendBuffer.data(), wavSendBuffer.size()); // WAVデータの送信
                        M5.Display.println("Sent to server!");

                        webSocket.loop(); // WebSocketの内部処理を即時実行
                        delay(10);
                    } else {
                        M5.Display.println("WebSocket not connected.");
                    }

                    // free(wavData);
                } else {
                    M5.Display.println("Failed to create WAV data.");
                }

                curState = REQUESTING;
            } else {
                M5.Display.println("WebSocket not connected.");
                curState = WAITING;
            }
            break;
        case REQUESTING:
        case RECEIVING_ACK:
        case RECEIVING_STREAM:
            delay(1); // WebSocketイベントを待機
            break;
        case PLAYING_ACK:
            if(!M5.Speaker.isPlaying()) { // 再生終了直後
                M5.Speaker.end(); // スピーカーを止める
                curState = REQUESTING;
                updateDisplay("Waiting for responce...");

                delay(100); // サーバー・クライアントのクールダウン
            }
            break;
        case PLAYING_STREAM:
            // 1. 再生中でない場合、次のキューを確認
            if (!M5.Speaker.isPlaying()) {
                if (!audioQueue.empty()) {
                    M5.Speaker.end(); // 念のため
                    M5.Speaker.begin();
                    M5.Speaker.setVolume(speaker_volume);

                    // キューの先頭を取り出して再生
                    Serial.println("Playing next sentence from queue...");
                    
                    // vectorのコピー（メモリ保護のため）
                    playingBuffer = audioQueue.front(); 
                    audioQueue.pop_front();

                    M5.Speaker.playRaw((const int16_t*)playingBuffer.data(), playingBuffer.size() / 2, 44100, false, 1);
                } 
                else if (is_response_completed) {
                    // キューが空かつ、サーバーからの送信完了通知済みなら終了
                    Serial.println("All sentences played.");
                    M5.Speaker.end();
                    curState = WAITING;
                    updateDisplay("Please press the button.");
                    is_response_completed = false; // リセット
                }
                else {
                    // キューは空だがサーバー送信がまだ終わっていない -> バッファリング待ち
                    // M5.Display.println("Buffering...");
                }
            }
            break;
        default:
            break;
    }
}
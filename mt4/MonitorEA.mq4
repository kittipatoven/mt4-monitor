//+------------------------------------------------------------------+
//| MonitorEA.mq4 - MT4 Trading Monitor V1 (READ-ONLY)                |
//|                                                                  |
//| Sends an account / order snapshot to the Raspberry Pi over       |
//| Tailscale. This EA NEVER calls OrderSend/OrderModify/OrderClose. |
//| Attach it to its own chart; do not touch the Capybara chart.      |
//|                                                                  |
//| Required: Tools > Options > Expert Advisors >                    |
//|   [x] Allow WebRequest for listed URL:  http://100.x.y.z (port 80, the Pi) |
//| API key: MQL4\Files\MonitorEA_key.txt (one line), or InpApiKey.  |
//+------------------------------------------------------------------+
#property copyright "MT4 Trading Monitor V1"
#property version   "1.00"
#property strict

input string InpUrl          = "http://100.x.y.z/api/update"; // Pi URL (Tailscale IP)
input string InpApiKey       = "";       // Leave empty to read MQL4\Files\MonitorEA_key.txt
input int    InpIntervalSec  = 5;                                   // Send every N seconds (>=2)
input int    InpTimeoutMs    = 3000;                                // HTTP timeout
input int    InpCapybaraMagic = -1;                                 // Capybara magic number (-1 = unknown)
input int    InpMaxOrders    = 50;                                  // Max orders per snapshot

#define KEY_FILE "MonitorEA_key.txt"

int    g_failStreak = 0;
bool   g_warnedUrl  = false;
string g_apiKey     = "";

//+------------------------------------------------------------------+
string LoadKeyFile()
  {
   int h = FileOpen(KEY_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return("");
   string k = FileReadString(h);
   FileClose(h);
   StringTrimLeft(k);
   StringTrimRight(k);
   return(k);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   g_apiKey = (InpApiKey != "") ? InpApiKey : LoadKeyFile();
   if(g_apiKey == "")
     {
      Alert("MonitorEA: no API key. Put it in MQL4\\Files\\" + KEY_FILE + " or set InpApiKey");
      return(INIT_PARAMETERS_INCORRECT);
     }
   int interval = MathMax(2, InpIntervalSec);
   if(!EventSetTimer(interval))
     {
      Print("MonitorEA: EventSetTimer failed, err=", GetLastError());
      return(INIT_FAILED);
     }
   Print("MonitorEA started. Sending to ", InpUrl, " every ", interval, "s (read-only).");
   SendSnapshot();
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

//+------------------------------------------------------------------+
void OnTick() { }   // work is done on the timer, independent of ticks

void OnTimer()
  {
   SendSnapshot();
  }

//+------------------------------------------------------------------+
string JsonEscape(string s)
  {
   string out = "";
   int n = StringLen(s);
   for(int i = 0; i < n; i++)
     {
      ushort c = StringGetCharacter(s, i);
      if(c == '"')       out += "\\\"";
      else if(c == '\\') out += "\\\\";
      else if(c < 32)    out += " ";
      else if(c > 126)   out += "?";          // keep payload plain ASCII
      else               out += ShortToString(c);
     }
   return(out);
  }

string JStr(string s)  { return("\"" + JsonEscape(s) + "\""); }
string JNum(double v, int digits) { return(DoubleToString(v, digits)); }
string JBool(bool b)   { return(b ? "true" : "false"); }

//+------------------------------------------------------------------+
string BuildJson()
  {
   double margin = AccountMargin();
   double equity = AccountEquity();
   double marginLevel = (margin > 0.0) ? equity / margin * 100.0 : 0.0;

   string acc = "{"
      + "\"login\":"        + IntegerToString(AccountNumber())
      + ",\"name\":"        + JStr(AccountName())
      + ",\"server\":"      + JStr(AccountServer())
      + ",\"company\":"     + JStr(AccountCompany())
      + ",\"currency\":"    + JStr(AccountCurrency())
      + ",\"leverage\":"    + IntegerToString(AccountLeverage())
      + ",\"balance\":"     + JNum(AccountBalance(), 2)
      + ",\"equity\":"      + JNum(equity, 2)
      + ",\"margin\":"      + JNum(margin, 2)
      + ",\"free_margin\":" + JNum(AccountFreeMargin(), 2)
      + ",\"margin_level\":"+ JNum(marginLevel, 2)
      + ",\"profit\":"      + JNum(AccountProfit(), 2)
      + "}";

   // Only things this EA can verify about the terminal itself.
   string term = "{"
      + "\"connected\":"      + JBool(IsConnected())
      + ",\"trade_allowed\":" + JBool((bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      + ",\"build\":"         + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD))
      + "}";

   string orders = "";
   int count = 0, capyOrders = 0;
   double capyProfit = 0.0;
   int total = OrdersTotal();
   for(int i = 0; i < total; i++)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      double p = OrderProfit() + OrderSwap() + OrderCommission();
      if(InpCapybaraMagic >= 0 && OrderMagicNumber() == InpCapybaraMagic)
        {
         capyOrders++;
         capyProfit += p;
        }
      if(count >= InpMaxOrders)
         continue;
      int digits = (int)MarketInfo(OrderSymbol(), MODE_DIGITS);
      if(count > 0) orders += ",";
      orders += "{"
         + "\"ticket\":"      + IntegerToString(OrderTicket())
         + ",\"symbol\":"     + JStr(OrderSymbol())
         + ",\"type\":"       + IntegerToString(OrderType())
         + ",\"lots\":"       + JNum(OrderLots(), 2)
         + ",\"open_price\":" + JNum(OrderOpenPrice(), digits)
         + ",\"sl\":"         + JNum(OrderStopLoss(), digits)
         + ",\"tp\":"         + JNum(OrderTakeProfit(), digits)
         + ",\"profit\":"     + JNum(p, 2)
         + ",\"magic\":"      + IntegerToString(OrderMagicNumber())
         + ",\"open_time\":"  + IntegerToString((long)OrderOpenTime())
         + "}";
      count++;
     }

   // Capybara status is ALWAYS "UNVERIFIED": MT4 offers no reliable API to
   // see whether another EA on another chart is running. Magic-number order
   // counts are evidence of past activity, not proof that it is running now.
   string capy = "{"
      + "\"status\":\"UNVERIFIED\""
      + ",\"magic_filter\":" + IntegerToString(InpCapybaraMagic)
      + ",\"magic_orders\":" + IntegerToString(capyOrders)
      + ",\"magic_profit\":" + JNum(capyProfit, 2)
      + "}";

   string mon = "{"
      + "\"version\":\"1.00\""
      + ",\"interval\":" + IntegerToString(InpIntervalSec)
      + ",\"orders_total\":" + IntegerToString(total)
      + "}";

   return("{"
      + "\"v\":1"
      + ",\"sent_at\":"     + IntegerToString((long)TimeGMT())
      + ",\"server_time\":" + IntegerToString((long)TimeCurrent())
      + ",\"monitor\":"     + mon
      + ",\"account\":"     + acc
      + ",\"terminal\":"    + term
      + ",\"capybara\":"    + capy
      + ",\"orders\":["     + orders + "]"
      + "}");
  }

//+------------------------------------------------------------------+
void SendSnapshot()
  {
   string json = BuildJson();

   char data[];
   char result[];
   string resultHeaders;
   int len = StringToCharArray(json, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(len > 0)
      ArrayResize(data, len - 1);   // drop the trailing '\0'

   string headers = "Content-Type: application/json\r\n"
                    + "X-API-Key: " + g_apiKey + "\r\n";

   ResetLastError();
   int status = WebRequest("POST", InpUrl, headers, InpTimeoutMs, data, result, resultHeaders);

   if(status == -1)
     {
      int err = GetLastError();
      if(err == 4060 && !g_warnedUrl)
        {
         Alert("MonitorEA: add the Pi URL to Tools > Options > Expert Advisors > Allow WebRequest");
         g_warnedUrl = true;
        }
      LogFailure("WebRequest failed, err=" + IntegerToString(err));
      return;
     }
   if(status != 200)
     {
      LogFailure("HTTP " + IntegerToString(status) + ": " + CharArrayToString(result));
      return;
     }
   if(g_failStreak > 0)
      Print("MonitorEA: connection to Pi restored after ", g_failStreak, " failures");
   g_failStreak = 0;
  }

//+------------------------------------------------------------------+
void LogFailure(string msg)
  {
   g_failStreak++;
   // Log 1st failure, then every 12th, so the journal is not flooded.
   if(g_failStreak == 1 || g_failStreak % 12 == 0)
      Print("MonitorEA: ", msg, " (streak ", g_failStreak, ")");
  }
//+------------------------------------------------------------------+

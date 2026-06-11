# -*- coding: utf-8 -*-
"""
===================================
OKX Fetcher - 加密货币数据源
===================================

数据来源：OKX 公开 API
特点：支持 BTC、ETH、SOL 等主流加密货币
定位：加密资产行情、K线数据聚合

支持的交易对格式：
- BTC-USDT（现货）
- BTC-USDC
- ETH-USDT
- SOL-USDT
- 等任意 OKX 支持的交易对

API 文档：https://www.okx.com/docs-v5/zh/
"""

import os
import logging
import requests
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# 标准数据列名
STANDARD_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'code']


class OkxFetcher:
    """OKX 加密货币数据源"""
    
    name = "OkxFetcher"
    priority = 5  # 数据源优先级（越低越优先）
    
    def __init__(self):
        self._base_url = "https://www.okx.com/api/v5"
        self._timeout = 15
        self._api_key = os.getenv('OKX_API_KEY', '')
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'daily-stock-analysis/crypto-module'
        })
        
        if self._api_key:
            self._session.headers.update({
                'OK-ACCESS-KEY': self._api_key
            })
    
    def is_available(self) -> bool:
        """
        检查数据源是否可用
        OKX 公开 API 无需认证
        """
        return True
    
    @staticmethod
    def is_crypto_symbol(symbol: str) -> bool:
        """
        判断是否为加密货币交易对
        格式：BTC-USDT、ETH-USDT 等
        """
        if not symbol or '-' not in symbol:
            return False
        parts = symbol.split('-')
        return len(parts) == 2 and parts[1].upper() in ['USDT', 'USDC', 'BUSD', 'DAI']
    
    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取加密货币实时行情
        
        Args:
            symbol: 交易对，如 'BTC-USDT', 'ETH-USDT'
            
        Returns:
            包含实时行情的字典，或 None
        """
        if not self.is_crypto_symbol(symbol):
            return None
        
        try:
            logger.debug(f"[OKX] 获取 {symbol} 实时行情")
            
            url = f"{self._base_url}/market/ticker"
            params = {"instId": symbol}
            
            response = self._session.get(url, params=params, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') != '0' or not data.get('data'):
                logger.warning(f"[OKX] 无法获取 {symbol} 行情: {data.get('msg')}")
                return None
            
            ticker = data['data'][0]
            
            current = self._safe_float(ticker.get('last'))
            prev_close = self._safe_float(ticker.get('open24h', current))
            change = current - prev_close if current and prev_close else None
            change_pct = (change / prev_close * 100) if change and prev_close else None
            
            result = {
                'code': symbol,
                'name': symbol,
                'current': current,
                'change': change,
                'change_pct': change_pct,
                'bid': self._safe_float(ticker.get('bidPx')),
                'ask': self._safe_float(ticker.get('askPx')),
                'volume': self._safe_float(ticker.get('vol24h')),
                'amount': self._safe_float(ticker.get('volCcy24h')),
                'open': self._safe_float(ticker.get('open24h')),
                'high': self._safe_float(ticker.get('high24h')),
                'low': self._safe_float(ticker.get('low24h')),
                'timestamp': int(ticker.get('ts', 0)) / 1000,
                'source': 'okx'
            }
            
            logger.info(f"[OKX] 获取 {symbol} 实时行情成功: {current}")
            return result
            
        except Exception as e:
            logger.error(f"[OKX] 获取 {symbol} 实时行情异常: {e}")
            return None
    
    def get_history_klines(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ) -> Optional[pd.DataFrame]:
        """
        获取加密货币历史 K 线
        
        Args:
            symbol: 交易对，如 'BTC-USDT'
            start_date: 开始日期 YYYYMMDD 或 YYYY-MM-DD
            end_date: 结束日期 YYYYMMDD 或 YYYY-MM-DD
            period: K线周期 'daily'/'4h'/'1h'/'30m'/'5m'/'1m'
            
        Returns:
            包含 OHLCV 数据的 DataFrame，或 None
        """
        if not self.is_crypto_symbol(symbol):
            return None
        
        try:
            logger.debug(f"[OKX] 获取 {symbol} K线 ({start_date}-{end_date}, 周期: {period})")
            
            # 转换周期格式
            bar_map = {
                "daily": "1D",
                "4h": "4H",
                "1h": "1H",
                "30m": "30m",
                "5m": "5m",
                "1m": "1m",
            }
            bar = bar_map.get(period, "1D")
            
            url = f"{self._base_url}/market/candles"
            
            # 转换时间戳（毫秒）
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                start_dt = datetime.strptime(start_date, "%Y%m%d")
                end_dt = datetime.strptime(end_date, "%Y%m%d")
            
            start_ts = int(start_dt.timestamp() * 1000)
            end_ts = int(end_dt.timestamp() * 1000)
            
            all_data = []
            current_ts = start_ts
            
            while current_ts < end_ts:
                params = {
                    "instId": symbol,
                    "bar": bar,
                    "after": current_ts,
                    "limit": 100  # 单次最多 100 条
                }
                
                response = self._session.get(url, params=params, timeout=self._timeout)
                response.raise_for_status()
                data = response.json()
                
                if data.get('code') != '0' or not data.get('data'):
                    logger.debug(f"[OKX] K线数据查询结束: {data.get('msg')}")
                    break
                
                candles = data['data']
                if not candles:
                    break
                
                for candle in candles:
                    if len(candle) < 7:
                        continue
                    
                    ts, open_p, high, low, close, vol, vol_ccy = candle[:7]
                    
                    ts_int = int(ts)
                    date_str = datetime.fromtimestamp(ts_int / 1000).strftime('%Y-%m-%d')
                    
                    open_f = self._safe_float(open_p)
                    close_f = self._safe_float(close)
                    
                    all_data.append({
                        'date': date_str,
                        'open': open_f,
                        'high': self._safe_float(high),
                        'low': self._safe_float(low),
                        'close': close_f,
                        'volume': self._safe_float(vol),
                        'amount': self._safe_float(vol_ccy),
                    })
                
                # 更新时间戳以获取下一批
                current_ts = int(candles[-1][0])
                
                # 防止无限循环
                if current_ts >= end_ts:
                    break
            
            if all_data:
                df = pd.DataFrame(all_data)
                
                # 计算涨跌幅
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                df['pct_chg'] = df['close'].pct_change() * 100
                df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
                df['code'] = symbol
                
                # 按标准列排序
                keep = ['code'] + STANDARD_COLUMNS
                df = df[[col for col in keep if col in df.columns]]
                
                logger.info(f"[OKX] 获取 {symbol} K线成功: {len(df)} 条记录")
                return df
            
            logger.warning(f"[OKX] 未获取到 {symbol} K线数据")
            return None
            
        except Exception as e:
            logger.error(f"[OKX] 获取 {symbol} K线异常: {e}")
            return None
    
    def get_stock_name(self, symbol: str) -> Optional[str]:
        """
        获取交易对名称
        OKX 格式通常为 BTC-USDT，直接返回
        """
        if self.is_crypto_symbol(symbol):
            return symbol
        return None
    
    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """安全浮点数转换"""
        try:
            if value is None or value == '':
                return None
            return float(value)
        except (ValueError, TypeError):
            return None


# 便利函数
def is_crypto_symbol(symbol: str) -> bool:
    """判断是否为加密货币交易对"""
    return OkxFetcher.is_crypto_symbol(symbol)

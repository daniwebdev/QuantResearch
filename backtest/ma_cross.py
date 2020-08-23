"""
Buy/sell when price crosses above/below SMA;
Close position when price crosses below/above SMA;
"""
import os
import numpy as np
import pandas as pd
import pytz
from datetime import datetime, timezone
import multiprocessing
import quanttrading2 as qt
import matplotlib.pyplot as plt
import empyrical as ep
"""
To use pyfolio 0.9.2
1. line 893 in pyfolio/timeseries.py from: valley = np.argmin(underwater)  # end of the period to valley = underwater.idxmin()   # end of the period
2. line 133 and 137 in pyfolio/round_trips.py: groupby uses list not tuple. ['block_dir', 'block_time']
3. line 77 in pyfolio/roud_trips.py: doesn't support agg(stats_dict) and rename_axis ==> rename
        ss = round_trips.assign(ones=1).groupby('ones')[col].agg(list(stats_dict.values()))
        ss.columns = list(stats_dict.keys())
        stats_all = (ss.T.rename({1.0: 'All trades'}, axis='columns'))
4. line 385, same for RETURN_STATS as in 3
5. utils print_table, add print(table) to use outside jupyter
6. line 840 in tears.py, add
        positions_bod = positions.sum(axis='columns') / (1 + returns)
        positions_bod.index = positions_bod.index.to_series().apply(lambda x: x.replace(hour=0, minute=0, second=0))
"""
import pyfolio as pf
import pickle
# set browser full width
from IPython.core.display import display, HTML
display(HTML("<style>.container { width:100% !important; }</style>"))


class MACross(qt.StrategyBase):
    def __init__(self,
            lookback=20
    ):
        super(MACross, self).__init__()
        self.lookback = lookback
        self.current_time = None
        self.current_position = 0

    def on_tick(self, tick_event):
        self.current_time = tick_event.timestamp
        # print('Processing {}'.format(self.current_time))
        symbol = self.symbols[0]

        df_hist = self._data_board.get_hist_price(symbol, tick_event.timestamp)
        current_price = df_hist.iloc[-1].Close

        # wait for enough bars
        if df_hist.shape[0] < self.lookback:
            return

        # Calculate the simple moving averages
        sma = np.mean(df_hist['Close'][-self.lookback:])
        # Trading signals based on moving average cross
        if current_price > sma and self.current_position <= 0:
            target_size = int((self._position_manager.cash + self.current_position * df_hist['Close'].iloc[-1])/df_hist['Close'].iloc[-1])       # buy to notional
            self.adjust_position(symbol, size_from=self.current_position, size_to=target_size, timestamp=self.current_time)
            print("Long: %s, sma %s, price %s, trade %s, new position %s" % (self.current_time, str(sma), str(current_price), str(target_size-self.current_position), str(target_size)))
            self.current_position = target_size
        elif current_price < sma and self.current_position >= 0:
            target_size = int((self._position_manager.cash + self.current_position * df_hist['Close'].iloc[-1])/df_hist['Close'].iloc[-1])*(-1)    # sell to notional
            self.adjust_position(symbol, size_from=self.current_position, size_to=target_size, timestamp=self.current_time)
            print("Short: %s, sma %s, price %s, trade %s, new position %s" % (self.current_time, str(sma), str(current_price), str(target_size-self.current_position), str(target_size)))
            self.current_position = target_size


def parameter_search(engine, tag, target_name, return_dict):
    """
    This function should be the same for all strategies.
    The only reason not included in quanttrading2 is because of its dependency on pyfolio (to get perf_stats)
    """
    ds_equity, _, _ = engine.run()
    try:
        strat_ret = ds_equity.pct_change().dropna()
        perf_stats_strat = pf.timeseries.perf_stats(strat_ret)
        target_value = perf_stats_strat.loc[target_name]  # first table in tuple
    except KeyError:
        target_value = 0
    return_dict[tag] = target_value


if __name__ == '__main__':
    do_optimize = False
    run_in_jupyter = False
    is_intraday = True
    symbol = 'SPX'
    benchmark = 'SPX'
    init_capital = 100_000.0

    if not is_intraday:
        test_start_date = datetime(2010, 1, 1, 8, 30, 0, 0, pytz.timezone('America/New_York'))
        test_end_date = datetime(2019, 12, 31, 6, 0, 0, 0, pytz.timezone('America/New_York'))
        datapath = os.path.join('../data/', f'{symbol}.csv')
        data = qt.util.read_ohlcv_csv(datapath)
    else:
        # it seems initialize timezone doesn't work
        eastern = pytz.timezone('US/Eastern')
        test_start_date = eastern.localize(datetime(2020, 8, 10, 9, 30, 0))
        test_end_date = eastern.localize(datetime(2020, 8, 10, 10, 0, 0))
        dict_hist_data = {}
        if os.path.isfile('../data/tick/20200810.pkl'):
            with open('../data/tick/20200810.pkl', 'rb') as f:
                dict_hist_data = pickle.load(f)
        data = dict_hist_data['ESU0 FUT GLOBEX']
        data.index = data.index.tz_localize('America/New_York')  # US/Eastern, UTC

    if do_optimize:          # parallel parameter search
        params_list = []
        for lk in [10, 20, 30, 50, 100, 200]:
            params_list.append({'lookback': lk})
        target_name = 'Sharpe ratio'
        manager = multiprocessing.Manager()
        return_dict = manager.dict()
        jobs = []
        for params in params_list:
            strategy = MACross()
            strategy.set_capital(init_capital)
            strategy.set_symbols([symbol])
            backtest_engine = qt.BacktestEngine(test_start_date, test_end_date)
            backtest_engine.set_capital(init_capital)  # capital or portfolio >= capital for one strategy
            backtest_engine.add_data(symbol, data)
            strategy.set_params({'lookback': params['lookback']})
            backtest_engine.set_strategy(strategy)
            tag = (params['lookback'])
            p = multiprocessing.Process(target=parameter_search, args=(backtest_engine, tag, target_name, return_dict))
            jobs.append(p)
            p.start()

        for proc in jobs:
            proc.join()
        for k,v in return_dict.items():
            print(k, v)
    else:
        strategy = MACross()
        strategy.set_capital(init_capital)
        strategy.set_symbols([symbol])
        strategy.set_params({'lookback':20})

        # Create a Data Feed
        backtest_engine = qt.BacktestEngine(test_start_date, test_end_date)
        backtest_engine.set_capital(init_capital)  # capital or portfolio >= capital for one strategy
        backtest_engine.add_data(symbol, data)
        backtest_engine.set_strategy(strategy)
        ds_equity, df_positions, df_trades = backtest_engine.run()
        # save to excel
        qt.util.save_one_run_results('./output', ds_equity, df_positions, df_trades)

        # ------------------------- Evaluation and Plotting -------------------------------------- #
        strat_ret = ds_equity.pct_change().dropna()
        strat_ret.name = 'strat'
        if not is_intraday:
            bm = qt.util.read_ohlcv_csv(os.path.join('../data/', f'{benchmark}.csv'))
        else:
            bm = data      # buy and hold
        bm_ret = bm['Close'].pct_change().dropna()
        bm_ret.index = pd.to_datetime(bm_ret.index)
        bm_ret = bm_ret[strat_ret.index]
        bm_ret.name = 'benchmark'

        perf_stats_strat = pf.timeseries.perf_stats(strat_ret)
        perf_stats_all = perf_stats_strat
        perf_stats_bm = pf.timeseries.perf_stats(bm_ret)
        perf_stats_all = pd.concat([perf_stats_strat, perf_stats_bm], axis=1)
        perf_stats_all.columns = ['Strategy', 'Benchmark']

        drawdown_table = pf.timeseries.gen_drawdown_table(strat_ret, 5)
        monthly_ret_table = ep.aggregate_returns(strat_ret, 'monthly')
        monthly_ret_table = monthly_ret_table.unstack().round(3)
        ann_ret_df = pd.DataFrame(ep.aggregate_returns(strat_ret, 'yearly'))
        ann_ret_df = ann_ret_df.unstack().round(3)

        print('-------------- PERFORMANCE ----------------')
        print(perf_stats_all)
        print('-------------- DRAWDOWN ----------------')
        print(drawdown_table)
        print('-------------- MONTHLY RETURN ----------------')
        print(monthly_ret_table)
        print('-------------- ANNUAL RETURN ----------------')
        print(ann_ret_df)

        if run_in_jupyter:
            pf.create_full_tear_sheet(
                strat_ret,
                benchmark_rets=bm_ret,
                positions=df_positions,
                transactions=df_trades,
                round_trips=False)
            plt.show()
        else:
            f1 = plt.figure(1)
            pf.plot_rolling_returns(strat_ret, factor_returns=bm_ret)
            f1.show()
            f2 = plt.figure(2)
            pf.plot_rolling_volatility(strat_ret, factor_returns=bm_ret)
            f2.show()
            f3 = plt.figure(3)
            pf.plot_rolling_sharpe(strat_ret)
            f3.show()
            f4 = plt.figure(4)
            pf.plot_drawdown_periods(strat_ret)
            f4.show()
            f5 = plt.figure(5)
            pf.plot_monthly_returns_heatmap(strat_ret)
            f5.show()
            f6 = plt.figure(6)
            pf.plot_annual_returns(strat_ret)
            f6.show()
            f7 = plt.figure(7)
            pf.plot_monthly_returns_dist(strat_ret)
            plt.show()
            f8 = plt.figure(8)
            pf.create_position_tear_sheet(strat_ret, df_positions)
            plt.show()
            f9 = plt.figure(9)
            pf.create_txn_tear_sheet(strat_ret, df_positions, df_trades)
            plt.show()
            f10 = plt.figure(10)
            pf.create_round_trip_tear_sheet(strat_ret, df_positions, df_trades)
            plt.show()
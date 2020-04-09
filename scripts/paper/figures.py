import datetime
import time as time_module
import sys
import os

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import scipy.stats
import theano
import matplotlib
import pymc3 as pm

try:
    import covid19_inference as cov19
except ModuleNotFoundError:
    sys.path.append("../..")
    import covid19_inference as cov19

# ------------------------------------------------------------------------------ #
# global settings and variables
# ------------------------------------------------------------------------------ #

# styling for prior distributions
prio_style = {
    "color": "#708090",
    "linewidth": 3,
    "label": "Prior",
}
# styling for posterior distributions
post_style = {
    "density": True,
    "color": "tab:orange",
    "label": "Posterior",
    "zorder": -2,
}

# set to None to keep everything a vector, with `-1` Posteriors are rastered (see above)
rasterization_zorder = -1

country = "Germany"
confirmed_cases = cov19.get_jhu_confirmed_cases()
date_data_begin = datetime.datetime(2020, 3, 1)
date_data_end = cov19.get_last_date(confirmed_cases)

# number of days in the data -1, to match the new cases
num_days_data = (date_data_end - date_data_begin).days
# how many days the simulation starts before the data
diff_data_sim = 16
# how many days to forecast
num_days_futu = 28
# days of simulation until forecast starts
diff_to_0 = num_days_data + diff_data_sim

date_begin_sim = date_data_begin - datetime.timedelta(days=diff_data_sim)
date_end_sim = date_data_end + datetime.timedelta(days=num_days_futu)
num_days_sim = (date_end_sim - date_begin_sim).days


cases_obs = cov19.filter_one_country(
    confirmed_cases, country, date_data_begin, date_data_end
)

# traces = None
# models = None

# ------------------------------------------------------------------------------ #
# main functions
# ------------------------------------------------------------------------------ #


def run_model_three_change_points():
    print(
        "Cases yesterday ({}): {} and "
        "day before yesterday: {}".format(date_data_end.isoformat(), *cases_obs[:-3:-1])
    )

    prior_date_mild_dist_begin = datetime.datetime(2020, 3, 9)
    prior_date_strong_dist_begin = datetime.datetime(2020, 3, 16)
    prior_date_contact_ban_begin = datetime.datetime(2020, 3, 23)

    change_points = [
        dict(
            pr_mean_date_begin_transient=prior_date_mild_dist_begin,
            pr_sigma_date_begin_transient=3,
            pr_median_lambda=0.2,
            pr_sigma_lambda=0.5,
        ),
        dict(
            pr_mean_date_begin_transient=prior_date_strong_dist_begin,
            pr_sigma_date_begin_transient=1,
            pr_median_lambda=1 / 8,
            pr_sigma_lambda=0.5,
        ),
        dict(
            pr_mean_date_begin_transient=prior_date_contact_ban_begin,
            pr_sigma_date_begin_transient=1,
            pr_median_lambda=1 / 8 / 2,
            pr_sigma_lambda=0.5,
        ),
    ]

    models = []
    for num_change_points in range(4):
        model = cov19.SIR_with_change_points(
            new_cases_obs=np.diff(cases_obs),
            change_points_list=change_points[:num_change_points],
            date_begin_simulation=date_begin_sim,
            num_days_sim=num_days_sim,
            diff_data_sim=diff_data_sim,
            N=83e6,
            priors_dict=None,
        )
        models.append(model)

    traces = []
    for model in models:
        traces.append(pm.sample(model=model, init="advi", tune=200, draws=500))

    return models, traces


def create_figure_0(save_to=None):
    global traces
    if traces is None:
        print(f"Have to run simulations first, this will take some time")
        _, traces = run_model_three_change_points()

    trace = traces[3]
    posterior = traces[1:]
    figs = []

    # ------------------------------------------------------------------------------ #
    # prior and posterior
    # ------------------------------------------------------------------------------ #

    fig, axes = plt.subplots(1, 4, figsize=(8, 2))
    figs.append(fig)

    limit_lambda = (-0.1, 0.5)
    bins_lambda = np.linspace(*limit_lambda, 30)

    # LAM 0
    ax = axes[0]
    ax.hist(trace.lambda_0 - trace.mu, bins=bins_lambda, **post_style)
    x = np.linspace(*limit_lambda, num=100)
    ax.plot(x, scipy.stats.lognorm.pdf(x + 1 / 8, scale=0.4, s=0.5), **prio_style)
    ax.set_xlim(*limit_lambda)
    ax.set_ylabel("Density")
    ax.set_xlabel("Effective\ngrowth rate $\lambda_0^*$")
    ax.text(
        0.05,
        0.95,
        print_median_CI(trace.lambda_0 - trace.mu, prec=2),
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
    )
    ax.set_ylim(0, 23)

    # LAM 1
    ax = axes[1]
    ax.hist(trace.lambda_1 - trace.mu, bins=bins_lambda, **post_style)
    x = np.linspace(*limit_lambda, num=100)
    ax.plot(x, scipy.stats.lognorm.pdf(x + 1 / 8, scale=0.2, s=0.5), **prio_style)
    ax.set_xlim(*limit_lambda)
    ax.set_xlabel("Effective\ngrowth rate $\lambda_1^*$")
    ax.text(
        0.05,
        0.95,
        print_median_CI(trace.lambda_1 - trace.mu, prec=2),
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
    )
    ax.set_ylim(0, 23)

    # TIME 1
    ax = axes[2]
    dates_mild = conv_time_to_mpl_dates(trace.transient_begin_0)
    limits = matplotlib.dates.date2num(
        [datetime.date(2020, 3, 2), datetime.date(2020, 3, 12)]
    )
    bins = np.arange(limits[0], limits[1] + 1)
    ax.hist(dates_mild, bins=bins, density=True, color="tab:orange", label="Posterior")
    x = np.linspace(*limits, num=1000)
    ax.plot(
        x,
        scipy.stats.norm.pdf(
            x, loc=matplotlib.dates.date2num([prior_date_mild_dist_begin])[0], scale=3
        ),
        **prio_style,
    )
    ax.set_xlim(limits[0], limits[1])
    ax.set_xlabel("Time begin\nmild dist. $t_1$")
    text = print_median_CI(
        dates_mild - matplotlib.dates.date2num(datetime.datetime(2020, 3, 1)) + 1,
        prec=1,
    )
    ax.text(
        0.05,
        0.95,
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
    )
    ax.xaxis.set_major_locator(
        matplotlib.dates.WeekdayLocator(byweekday=matplotlib.dates.SU)
    )
    ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
    ax.set_ylim(0, 0.45)

    # TIME 2
    ax = axes[3]
    dates_strong = conv_time_to_mpl_dates(trace.transient_begin_1)
    limits = matplotlib.dates.date2num(
        [datetime.date(2020, 3, 13), datetime.date(2020, 3, 23)]
    )
    bins = np.arange(limits[0], limits[1] + 1)
    ax.hist(
        dates_strong, bins=bins, density=True, color="tab:orange", label="Posterior"
    )
    # limits = ax.get_xlim()
    x = np.linspace(*limits, num=1000)
    ax.plot(
        x,
        scipy.stats.norm.pdf(
            x, loc=matplotlib.dates.date2num([prior_date_strong_dist_begin])[0], scale=1
        ),
        **prio_style,
    )
    ax.set_xlim(limits[0], limits[1])
    ax.set_ylabel("Density")
    ax.set_xlabel("Time begin\nstrong dist. $t_2$")
    text = print_median_CI(
        dates_strong - matplotlib.dates.date2num(datetime.datetime(2020, 3, 1)) + 1,
        prec=1,
    )
    ax.text(
        0.05,
        0.95,
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
    )
    # ax.xaxis.set_major_locator(matplotlib.dates.AutoDateLocator())
    ax.xaxis.set_major_locator(
        matplotlib.dates.WeekdayLocator(byweekday=matplotlib.dates.SU)
    )
    ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
    ax.set_ylim(0, 0.45)
    ax.set_xlim(limits[0], limits[1])

    for ax in axes:
        ax.set_rasterization_zorder(rasterization_zorder)

    if save_to is not None:
        fig.savefig(save_to + "_summary_distributions.png", dpi=300)
        fig.savefig(save_to + "_summary_distributions.pdf", dpi=300)

    # ------------------------------------------------------------------------------ #
    # time series
    # ------------------------------------------------------------------------------ #

    fig, axes = plt.subplots(
        3, 1, figsize=(6.5, 7.5), gridspec_kw={"height_ratios": [2, 2, 2]}
    )
    figs.append(fig)

    pos_letter = (-0.275, 0.98)
    colors = ["tab:red", "tab:orange", "tab:green"]
    legends = [
        r"$\bf{Forecasts:}$",
        "one change point",
        "two change points",
        "three change points",
    ]

    # NEW CASES
    ax = axes[1]
    time1 = np.arange(-len(cases_obs) + 2, 1)
    mpl_dates = conv_time_to_mpl_dates(time1) + diff_data_sim + num_days_data
    start_date = mpl_dates[0]
    diff_cases = np.diff(cases_obs)
    ax.plot(
        mpl_dates,
        diff_cases,
        "d",
        label="Confirmed new cases",
        markersize=4,
        color="tab:blue",
        zorder=5,
    )
    new_cases_past = trace.new_cases[:, :num_days_data]
    percentiles = (
        np.percentile(new_cases_past, q=2.5, axis=0),
        np.percentile(new_cases_past, q=97.5, axis=0),
    )
    ax.plot(
        mpl_dates,
        np.median(new_cases_past, axis=0),
        color="tab:green",
        linewidth=3,
        zorder=0,
    )
    ax.fill_between(
        mpl_dates, percentiles[0], percentiles[1], alpha=0.3, color="tab:green", lw=0
    )
    ax.plot([], [], label=legends[0], alpha=0)

    for trace_scen, color, legend in zip(posterior, colors, legends[1:]):
        new_cases_past = trace_scen.new_cases[:, :num_days_data]
        ax.plot(
            mpl_dates,
            np.median(new_cases_past, axis=0),
            "--",
            color=color,
            linewidth=1.5,
        )
        time2 = np.arange(0, num_days_futu + 1)
        mpl_dates_fut = conv_time_to_mpl_dates(time2) + diff_data_sim + num_days_data
        end_date = mpl_dates_fut[-10]
        cases_futu = trace_scen["new_cases"][:, num_days_data:].T
        median = np.median(cases_futu, axis=-1)
        percentiles = (
            np.percentile(cases_futu, q=2.5, axis=-1),
            np.percentile(cases_futu, q=97.5, axis=-1),
        )
        ax.plot(mpl_dates_fut[1:], median, color=color, linewidth=3, label=legend)
        ax.fill_between(
            mpl_dates_fut[1:],
            percentiles[0],
            percentiles[1],
            alpha=0.15,
            color=color,
            lw=0,
        )

    ax.set_xlabel("Date")
    ax.set_ylabel("New confirmed cases\nin Germany")
    ax.text(pos_letter[0], pos_letter[1], "B", transform=ax.transAxes, size=20)
    ax.legend(loc="upper left")
    ax.set_ylim(0, 15_000)
    ax.locator_params(axis="y", nbins=4)
    func_format = lambda num, _: "${:.0f}\,$k".format(num / 1_000)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(func_format))
    ax.xaxis.set_major_locator(
        matplotlib.dates.WeekdayLocator(byweekday=matplotlib.dates.SU)
    )
    ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
    ax.set_xlim(start_date, end_date)
    ax.xaxis.set_ticks_position("both")

    # TOTAL CASES
    ax = axes[2]
    time1 = np.arange(-len(cases_obs) + 2, 1)
    mpl_dates = conv_time_to_mpl_dates(time1) + diff_data_sim + num_days_data
    ax.plot(
        mpl_dates,
        cases_obs[1:],
        "d",
        label="Confirmed cases",
        markersize=4,
        color="tab:blue",
        zorder=5,
    )
    cum_cases = np.cumsum(new_cases_past, axis=1) + cases_obs[0]
    percentiles = (
        np.percentile(cum_cases, q=2.5, axis=0),
        np.percentile(cum_cases, q=97.5, axis=0),
    )
    ax.plot(
        mpl_dates,
        np.median(cum_cases, axis=0),
        color="tab:green",
        linewidth=3,
        zorder=0,
    )
    ax.fill_between(
        mpl_dates, percentiles[0], percentiles[1], alpha=0.3, color="tab:green", lw=0,
    )
    ax.plot([], [], label=legends[0], alpha=0)

    for trace_scen, color, legend in zip(posterior, colors, legends[1:]):
        new_cases_past = trace_scen.new_cases[:, :num_days_data]
        cum_cases = np.cumsum(new_cases_past, axis=1) + cases_obs[0]
        ax.plot(
            mpl_dates, np.median(cum_cases, axis=0), "--", color=color, linewidth=1.5
        )

        time2 = np.arange(0, num_days_futu + 1)
        mpl_dates_fut = conv_time_to_mpl_dates(time2) + diff_data_sim + num_days_data
        cases_futu = (
            np.cumsum(trace_scen["new_cases"][:, num_days_data:].T, axis=0)
            + cases_obs[-1]
        )
        median = np.median(cases_futu, axis=-1)
        percentiles = (
            np.percentile(cases_futu, q=2.5, axis=-1),
            np.percentile(cases_futu, q=97.5, axis=-1),
        )
        ax.plot(mpl_dates_fut[1:], median, color=color, linewidth=3, label=legend)
        ax.fill_between(
            mpl_dates_fut[1:],
            percentiles[0],
            percentiles[1],
            alpha=0.15,
            color=color,
            lw=0,
        )

    ax.set_xlabel("Date")
    ax.set_ylabel("Total confirmed cases\nin Germany")
    ax.text(pos_letter[0], pos_letter[1], "C", transform=ax.transAxes, size=20)
    ax.legend(loc="upper left")
    ax.set_ylim(0, 200_000)
    ax.locator_params(axis="y", nbins=4)
    func_format = lambda num, _: "${:.0f}\,$k".format(num / 1_000)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(func_format))
    ax.set_xlim(start_date, end_date)
    ax.xaxis.set_major_locator(
        matplotlib.dates.WeekdayLocator(byweekday=matplotlib.dates.SU)
    )
    ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
    ax.set_xlim(start_date, end_date)

    # LAMBDA
    ax = axes[0]
    time = np.arange(-diff_to_0 + 1, -diff_to_0 + num_days_sim + 1)

    for trace_scen, color in zip(posterior, colors):
        lambda_t = trace_scen["lambda_t"][:, :]
        mu = trace_scen["mu"][:, None]
        mpl_dates = conv_time_to_mpl_dates(time) + diff_data_sim + num_days_data

        ax.plot(mpl_dates, np.median(lambda_t - mu, axis=0), color=color, linewidth=2)
        ax.fill_between(
            mpl_dates,
            np.percentile(lambda_t - mu, q=2.5, axis=0),
            np.percentile(lambda_t - mu, q=97.5, axis=0),
            alpha=0.15,
            color=color,
            lw=0,
        )

    ax.set_ylabel("Effective\ngrowth rate $\lambda_t^*$")
    ax.text(pos_letter[0], pos_letter[1], "A", transform=ax.transAxes, size=20)
    ax.set_ylim(-0.15, 0.45)
    ax.hlines(0, start_date, end_date, linestyles=":")
    delay = matplotlib.dates.date2num(date_data_end) - np.percentile(trace.delay, q=75)
    ax.vlines(delay, -10, 10, linestyles="-", colors=["tab:red"])
    ax.text(
        delay + 0.4,
        0.4,
        "unconstrained because\nof reporting delay",
        color="tab:red",
        verticalalignment="top",
    )
    ax.text(
        delay - 0.4,
        0.4,
        "constrained \nby data",
        color="tab:red",
        horizontalalignment="right",
        verticalalignment="top",
    )
    ax.xaxis.set_major_locator(
        matplotlib.dates.WeekdayLocator(byweekday=matplotlib.dates.SU)
    )
    ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
    ax.set_xlim(start_date, end_date)
    ax.xaxis.set_ticks_position("both")

    # FINALIZE
    axes[0].set_title(
        "COVID-19 in {} (as of {})".format(
            country, (date_data_end + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
        )
    )
    fig.subplots_adjust(hspace=-0.90)
    fig.tight_layout()

    for ax in axes:
        ax.set_rasterization_zorder(rasterization_zorder)

    if save_to is not None:
        fig.savefig(save_to + "_summary_forecast.pdf", dpi=300)
        fig.savefig(save_to + "_summary_forecast.png", dpi=300)

    return figs


def create_figure_3_timeseries(save_to=None):
    global traces
    if traces is None:
        print(f"Have to run simulations first, this will take some time")
        _, traces = run_model_three_change_points()

    ylabel_new = f"New daily confirmed\ncases in {country}"
    ylabel_cum = f"Total confirmed cases\nin {country}"

    pos_letter = (-0.3, 1)
    titlesize = 16

    # format 10_000 as 10 k
    format_k = lambda num, _: "${:.0f}\,$k".format(num / 1_000)

    # interval for the plots with forecast
    start_date = conv_time_to_mpl_dates(-len(cases_obs) + 2) + diff_to_0
    end_date = conv_time_to_mpl_dates(num_days_futu - 10) + diff_to_0
    mid_date = conv_time_to_mpl_dates(1) + diff_to_0

    # x-axis for dates, new_cases are one element shorter than cum_cases, use [1:]
    # 0 is the last recorded data point
    time_past = np.arange(-len(cases_obs) + 1, 1)
    time_futu = np.arange(0, num_days_futu + 1)
    mpl_dates_past = conv_time_to_mpl_dates(time_past) + diff_to_0
    mpl_dates_futu = conv_time_to_mpl_dates(time_futu) + diff_to_0

    figs = []
    for trace, color, save_name in zip(
        (traces[1:]),
        ("tab:red", "tab:orange", "tab:green"),
        ("Fig_S1", "Fig_3", "Fig_S3"),
    ):

        fig, axes = plt.subplots(
            3, 1, figsize=(8, 8), gridspec_kw={"height_ratios": [1, 3, 3]},
        )
        figs.append(fig)

        # PREPARE DATA
        # observed data, only one dim: [day]
        new_c_obsd = np.diff(cases_obs)
        cum_c_obsd = cases_obs

        # model traces, dims: [sample, day],
        new_c_past = trace["new_cases"][:, :num_days_data]
        new_c_futu = trace["new_cases"][:, num_days_data:]
        cum_c_past = (
            np.cumsum(np.insert(new_c_past, 0, 0, axis=1), axis=1) + cases_obs[0]
        )
        cum_c_futu = (
            np.cumsum(np.insert(new_c_futu, 0, 0, axis=1), axis=1) + cases_obs[-1]
        )

        # NEW CASES LIN SCALE
        ax = axes[1]
        ax.plot(
            mpl_dates_past[1:],
            new_c_obsd,
            "d",
            label="Data",
            markersize=4,
            color="tab:blue",
            zorder=5,
        )
        ax.plot(
            mpl_dates_past[1:],
            np.median(new_c_past, axis=0),
            "--",
            color=color,
            linewidth=1.5,
            label="Fit with 95% CI",
        )
        ax.fill_between(
            mpl_dates_past[1:],
            np.percentile(new_c_past, q=2.5, axis=0),
            np.percentile(new_c_past, q=97.5, axis=0),
            alpha=0.1,
            color=color,
            lw=0,
        )

        ax.plot(
            mpl_dates_futu[1:],
            np.median(new_c_futu, axis=0),
            color=color,
            linewidth=3,
            label="Forecast with 75% and 95% CI",
        )
        ax.fill_between(
            mpl_dates_futu[1:],
            np.percentile(new_c_futu, q=2.5, axis=0),
            np.percentile(new_c_futu, q=97.5, axis=0),
            alpha=0.1,
            color=color,
            lw=0,
        )
        ax.fill_between(
            mpl_dates_futu[1:],
            np.percentile(new_c_futu, q=12.5, axis=0),
            np.percentile(new_c_futu, q=87.5, axis=0),
            alpha=0.2,
            color=color,
            lw=0,
        )
        ax.set_xlabel("Date")
        ax.set_ylabel(ylabel_new)
        ax.legend(loc="upper left")
        ax.set_ylim(0, 15_000)
        ax.set_xlim(start_date, end_date)
        ax.text(
            pos_letter[0], pos_letter[1], "D", transform=ax.transAxes, size=titlesize
        )

        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(format_k))
        ax.set_xlim(start_date, end_date)
        ax.xaxis.set_major_locator(
            matplotlib.dates.WeekdayLocator(interval=2, byweekday=matplotlib.dates.SU)
        )
        ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))

        # NEW CASES LOG SCALE, skip forecast
        ax = inset_axes(ax, width="30%", height="30%", loc=2)
        ax.plot(
            mpl_dates_past[1:], new_c_obsd, "d", markersize=4, label="Data", zorder=5
        )
        ax.plot(
            mpl_dates_past[1:],
            np.median(new_c_past, axis=0),
            color=color,
            label="Fit (with 95% CI)",
        )
        ax.fill_between(
            mpl_dates_past[1:],
            np.percentile(new_c_past, q=2.5, axis=0),
            np.percentile(new_c_past, q=97.5, axis=0),
            alpha=0.1,
            color=color,
            lw=0,
        )
        ax.set_yscale("log")
        ax.set_ylabel(ylabel_new)
        ax.xaxis.set_major_locator(
            matplotlib.dates.WeekdayLocator(byweekday=matplotlib.dates.SU)
        )
        ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
        ax.set_xlim(start_date, mid_date)

        ax.legend()

        # TOTAL CASES LOG SCALE
        # ax = axes[2]
        # ax.plot(mpl_dates, cases_obs[1:], "d", markersize=4, label="Data", zorder=5)
        # cum_cases = np.cumsum(new_cases_past, axis=1) + cases_obs[0]
        # percentiles = (
        #     np.percentile(cum_cases, q=2.5, axis=0),
        #     np.percentile(cum_cases, q=97.5, axis=0),
        # )
        # ax.plot(
        #     mpl_dates,
        #     np.median(cum_cases, axis=0),
        #     color=color,
        #     label="Fit (with 95% CI)",
        # )
        # ax.fill_between(
        #     mpl_dates, percentiles[0], percentiles[1], alpha=0.3, color=color, lw=0
        # )
        # ax.set_yscale("log")
        # ax.set_ylabel(ylabel_cum)
        # ax.set_xlabel("Date")
        # ax.legend()
        # ax.text(
        #     pos_letter[0], pos_letter[1], "B", transform=ax.transAxes, size=titlesize
        # )
        # ax.xaxis.set_major_locator(
        #     matplotlib.dates.WeekdayLocator(interval=2, byweekday=matplotlib.dates.SU)
        # )
        # ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
        # ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
        # ax.set_xlim(mpl_dates[0])

        # TOTAL CASES LIN SCALE
        # ax = axes[2]
        # time1 = np.arange(-len(cases_obs) + 2, 1)
        # mpl_dates = conv_time_to_mpl_dates(time1) + diff_data_sim + num_days_data
        # ax.plot(
        #     mpl_dates,
        #     cases_obs[1:],
        #     "d",
        #     label="Confirmed cases",
        #     markersize=4,
        #     color="tab:blue",
        #     zorder=5,
        # )
        # ax.plot(
        #     mpl_dates,
        #     np.median(cum_cases, axis=0),
        #     "--",
        #     color=color,
        #     linewidth=1.5,
        #     label="Fit with 95% CI",
        # )
        # percentiles = (
        #     np.percentile(cum_cases, q=2.5, axis=0),
        #     np.percentile(cum_cases, q=97.5, axis=0),
        # )
        # ax.fill_between(
        #     mpl_dates, percentiles[0], percentiles[1], alpha=0.2, color=color, lw=0
        # )
        # time2 = np.arange(0, num_days_futu + 1)
        # mpl_dates_fut = conv_time_to_mpl_dates(time2) + diff_data_sim + num_days_data
        # median = np.median(cases_futu, axis=-1)
        # percentiles = (
        #     np.percentile(cases_futu, q=2.5, axis=-1),
        #     np.percentile(cases_futu, q=97.5, axis=-1),
        # )
        # ax.plot(
        #     mpl_dates_fut[1:],
        #     median,
        #     color=color,
        #     linewidth=3,
        #     label="Forecast with 75% and 95% CI",
        # )
        # ax.fill_between(
        #     mpl_dates_fut[1:],
        #     percentiles[0],
        #     percentiles[1],
        #     alpha=0.1,
        #     color=color,
        #     lw=0,
        # )
        # ax.fill_between(
        #     mpl_dates_fut[1:],
        #     np.percentile(cases_futu, q=12.5, axis=-1),
        #     np.percentile(cases_futu, q=87.5, axis=-1),
        #     alpha=0.2,
        #     color=color,
        #     lw=0,
        # )
        # ax.set_xlabel("Date")
        # ax.set_ylabel(ylabel_cum)
        # ax.legend(loc="upper left")
        # ax.set_ylim(0, 200_000)
        # func_format = lambda num, _: "${:.0f}\,$k".format(num / 1_000)
        # ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(func_format))
        # ax.set_xlim(start_date, end_date)
        # ax.xaxis.set_major_locator(
        #     matplotlib.dates.WeekdayLocator(interval=2, byweekday=matplotlib.dates.SU)
        # )
        # ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
        # ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
        # ax.set_xlim(start_date, end_date)
        # ax.text(
        #     pos_letter[0], pos_letter[1], "E", transform=ax.transAxes, size=titlesize
        # )

        # GROWTH RATE LAMBDA*
        ax = axes[0]
        time = np.arange(-diff_to_0 + 1, -diff_to_0 + num_days_sim + 1)
        lambda_t = trace["lambda_t"][:, :]
        mu = trace["mu"][:, None]
        mpl_dates = conv_time_to_mpl_dates(time) + diff_data_sim + num_days_data
        ax.plot(mpl_dates, np.median(lambda_t - mu, axis=0), color=color, linewidth=2)
        ax.fill_between(
            mpl_dates,
            np.percentile(lambda_t - mu, q=2.5, axis=0),
            np.percentile(lambda_t - mu, q=97.5, axis=0),
            alpha=0.15,
            color=color,
            lw=0,
        )
        ax.set_ylabel("Effective\ngrowth rate $\lambda_t^*$")
        ax.set_ylim(-0.15, 0.45)
        ax.hlines(0, start_date, end_date, linestyles=":")
        delay = matplotlib.dates.date2num(date_data_end) - np.percentile(
            trace.delay, q=75
        )
        ax.vlines(delay, -10, 10, linestyles="-", colors=["tab:red"])
        ax.text(
            delay + 0.5,
            0.4,
            "unconstrained because\nof reporting delay",
            color="tab:red",
            verticalalignment="top",
        )
        ax.text(
            delay - 0.5,
            0.4,
            "constrained\nby data",
            color="tab:red",
            horizontalalignment="right",
            verticalalignment="top",
        )
        ax.text(
            pos_letter[0], pos_letter[1], "C", transform=ax.transAxes, size=titlesize
        )
        ax.xaxis.set_major_locator(
            matplotlib.dates.WeekdayLocator(interval=2, byweekday=matplotlib.dates.SU)
        )
        ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))
        ax.set_xlim(start_date, end_date)

        # FINALIZE
        plt.subplots_adjust(wspace=0.4, hspace=0.3)
        if save_to is not None:
            plt.savefig(
                save_to + save_name + ".pdf",
                dpi=300,
                bbox_inches="tight",
                pad_inches=0,
            )
            plt.savefig(
                save_to + save_name + ".png",
                dpi=300,
                bbox_inches="tight",
                pad_inches=0,
            )

    return figs


def create_figure_3_distributions(save_to=None):
    trace = traces[2]
    colors = ["#708090", "tab:orange"]

    fig, axes = plt.subplots(4, 3, figsize=(5, 8))
    # plt.locator_params(nbins=4)
    pos_letter = (-0.1, 1.3)
    pos_median = (0.05, 0.9)
    size_letters = 14
    alpha_texbox = 0.3
    font_text = 9

    # LAM 0
    limit_lambda = (0, 0.53)
    ax = axes[0][0]
    ax.hist(trace.lambda_0, bins=50, density=True, color=colors[1], label="Posterior")
    limits = ax.get_xlim()
    x = np.linspace(*limit_lambda, num=100)
    ax.plot(
        x,
        scipy.stats.lognorm.pdf(x, scale=0.4, s=0.5),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limit_lambda)
    ax.set_xlabel("Initial\nspreading rate $\lambda_0$")
    text = print_median_CI(trace.lambda_0, prec=2)
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    ax.text(
        pos_letter[0],
        pos_letter[1],
        "F",
        transform=ax.transAxes,
        size=size_letters,
        horizontalalignment="right",
    )

    # INIT INFECTIONS
    ax = axes[0][1]
    ax.hist(trace.I_begin, bins=50, color=colors[1], density=True, label="Posterior")
    ax.set_xlabel("Initial number\nof infections $I_0$")
    limits = ax.get_xlim()
    x = np.linspace(*limits, num=5000)
    ax.plot(
        x,
        scipy.stats.halfcauchy.pdf(x, scale=100),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limits)
    ax.set_xlim(0)
    text = print_median_CI(trace.I_begin, prec=0)
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    # ax.text(pos_letter[0], pos_letter[1], "K", transform=ax.transAxes, size=size_letters)
    plt.subplots_adjust(hspace=0.5)

    # LAM 1
    ax = axes[1][0]
    ax.hist(trace.lambda_1, bins=50, density=True, color=colors[1], label="Posterior")
    limits = ax.get_xlim()
    x = np.linspace(*limit_lambda, num=100)
    ax.plot(
        x,
        scipy.stats.lognorm.pdf(x, scale=0.2, s=0.5),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limit_lambda)
    ax.set_xlabel("Mild distancing\nspreading rate $\lambda_1$")
    text = print_median_CI(trace.lambda_1, prec=2)
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    ax.text(
        pos_letter[0],
        pos_letter[1],
        "G1",
        transform=ax.transAxes,
        size=size_letters,
        horizontalalignment="right",
    )

    dates_mild = conv_time_to_mpl_dates(trace.transient_begin_0)

    # TIME 1
    ax = axes[1][1]
    ax.hist(dates_mild, bins=50, density=True, color=colors[1], label="Posterior")
    limits = ax.get_xlim()
    x = np.linspace(*limits, num=100)
    ax.plot(
        x,
        scipy.stats.norm.pdf(
            x, loc=matplotlib.dates.date2num([prior_date_mild_dist_begin])[0], scale=3
        ),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limits)
    ax.set_xlabel("Mild distancing\nstarting time $t_1$")
    text = print_median_CI(
        dates_mild - matplotlib.dates.date2num(datetime.datetime(2020, 3, 1)) + 1,
        prec=1,
    )
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    # ax.text(pos_letter[0], pos_letter[1], "E", transform=ax.transAxes, size=size_letters)
    ax.xaxis.set_major_locator(matplotlib.dates.DayLocator(interval=6))
    ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))

    # Transient T1
    ax = axes[1][2]
    ax.hist(
        trace.transient_len_0, bins=50, density=True, color=colors[1], label="Posterior"
    )
    limits = ax.get_xlim()
    x = np.linspace(*limits, num=100)
    ax.plot(
        x,
        scipy.stats.lognorm.pdf(x, scale=3, s=0.3),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limits)
    # ax.set_ylabel('Density')
    ax.set_xlabel("Mild distancing\ntransient $\Delta t_1$")
    text = print_median_CI(trace.transient_len_0, prec=1)
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    # ax.text(pos_letter[0], pos_letter[1], "G", transform=ax.transAxes, size=size_letters)

    # LAM 2
    ax = axes[2][0]
    ax.hist(trace.lambda_2, bins=50, density=True, color=colors[1], label="Posterior")
    limits = ax.get_xlim()
    x = np.linspace(*limit_lambda, num=100)
    ax.plot(
        x,
        scipy.stats.lognorm.pdf(x, scale=1 / 8, s=0.2),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limit_lambda)
    ax.set_xlabel("Strong distancing\nspreading rate $\lambda_2$")
    text = print_median_CI(trace.lambda_2, prec=2)
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    ax.text(
        pos_letter[0],
        pos_letter[1],
        "G2",
        transform=ax.transAxes,
        size=size_letters,
        horizontalalignment="right",
    )

    # TIME 2
    ax = axes[2][1]
    dates_strong = conv_time_to_mpl_dates(trace.transient_begin_1)

    ax.hist(dates_strong, bins=50, density=True, color=colors[1], label="Posterior")
    limits = ax.get_xlim()
    x = np.linspace(*limits, num=100)
    ax.plot(
        x,
        scipy.stats.norm.pdf(
            x, loc=matplotlib.dates.date2num([prior_date_strong_dist_begin])[0], scale=1
        ),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limits)
    ax.set_xlabel("Strong distancing\nstarting time $t_2$")
    text = print_median_CI(
        dates_strong - matplotlib.dates.date2num(datetime.datetime(2020, 3, 1)) + 1,
        prec=1,
    )
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    # ax.text(pos_letter[0], pos_letter[1], "F", transform=ax.transAxes, size=size_letters)
    ax.xaxis.set_major_locator(matplotlib.dates.DayLocator(interval=4))
    ax.xaxis.set_minor_locator(matplotlib.dates.DayLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%d"))

    # Transient T2
    ax = axes[2][2]
    ax.hist(
        trace.transient_len_1, bins=50, density=True, color=colors[1], label="Posterior"
    )
    limits = ax.get_xlim()
    x = np.linspace(*limits, num=100)
    ax.plot(
        x,
        scipy.stats.lognorm.pdf(x, scale=3, s=0.3),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limits)
    ax.set_xlabel("Strong distancing\ntransient $\Delta t_2$")
    text = print_median_CI(trace.transient_len_1, prec=1)
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    # ax.text(pos_letter[0], pos_letter[1], "H", transform=ax.transAxes, size=size_letters)

    # RECOVERY
    ax = axes[3][0]
    ax.hist(trace.mu, bins=50, density=True, color=colors[1], label="Posterior")
    limits = ax.get_xlim()
    x = np.linspace(*limits, num=100)
    ax.plot(
        x,
        scipy.stats.lognorm.pdf(x, scale=1 / 8, s=0.2),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limits)
    # ax.set_ylabel('Density')
    ax.set_xlabel("Recovery rate $\mu$")
    text = print_median_CI(trace.mu, prec=2)
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    ax.text(
        pos_letter[0],
        pos_letter[1],
        "H",
        transform=ax.transAxes,
        size=size_letters,
        horizontalalignment="right",
    )

    # WIDTH
    ax = axes[3][1]
    ax.hist(trace.sigma_obs, bins=50, color=colors[1], density=True, label="Posterior")
    # ax.set_ylabel('Density')
    ax.set_xlabel("Width $\sigma$\nof the likelihood")
    limits = ax.get_xlim()
    x = np.linspace(*limits, num=100)
    ax.plot(
        x,
        scipy.stats.halfcauchy.pdf(x, scale=10),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limits)
    text = print_median_CI(trace.sigma_obs, prec=1)
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    # ax.text(pos_letter[0], pos_letter[1], "J", transform=ax.transAxes, size=size_letters)

    # DELAY
    ax = axes[3][2]
    ax.hist(trace.delay, bins=50, density=True, color=colors[1], label="Posterior")
    limits = ax.get_xlim()
    x = np.linspace(*limits, num=100)
    ax.plot(
        x,
        scipy.stats.lognorm.pdf(x, scale=8, s=0.2),
        label="Prior",
        color=colors[0],
        linewidth=3,
    )
    ax.set_xlim(*limits)
    ax.set_xlabel("Delay $D$")
    text = print_median_CI(trace.delay, prec=1)
    ax.text(
        pos_median[0],
        pos_median[1],
        text,
        horizontalalignment="left",
        verticalalignment="top",
        transform=ax.transAxes,
        bbox=dict(facecolor="white", alpha=alpha_texbox, edgecolor="none"),
        fontsize=font_text,
    )
    # ax.text(pos_letter[0], pos_letter[1], "I", transform=ax.transAxes, size=size_letters)

    # plt.tight_layout()

    ax = axes[0][2]
    ax.set_visible(False)
    ax.plot([], [], color="#708090", linewidth=3)
    ax.hist([0], color="tab:orange")
    ax.legend()

    for ax_row in axes:
        for idx, ax in enumerate(ax_row):
            if idx == 0:
                ax.set_ylabel("Density")
            ax.tick_params(labelleft=False)
            ax.locator_params(nbins=4)
            ax.xaxis.set_label_position("top")

    plt.subplots_adjust(wspace=0.2, hspace=0.9)

    if save_to is not None:
        plt.savefig(save_to + ".pdf", bbox_inches="tight", pad_inches=0, dpi=300)
        plt.savefig(save_to + ".png", bbox_inches="tight", pad_inches=0, dpi=300)

    return fig


# ------------------------------------------------------------------------------ #
# helper
# ------------------------------------------------------------------------------ #


def truncate_number(number, precision):
    return "{{:.{}f}}".format(precision).format(number)


def print_median_CI(arr, prec=2):
    f_trunc = lambda n: truncate_number(n, prec)
    med = f_trunc(np.median(arr))
    perc1, perc2 = (
        f_trunc(np.percentile(arr, q=2.5)),
        f_trunc(np.percentile(arr, q=97.5)),
    )
    return "Median: {}\nCI: [{}, {}]".format(med, perc1, perc2)


def conv_time_to_mpl_dates(arr):
    try:
        return matplotlib.dates.date2num(
            [datetime.timedelta(days=float(date)) + date_begin_sim for date in arr]
        )
    except:
        return matplotlib.dates.date2num(
            datetime.timedelta(days=float(arr)) + date_begin_sim
        )

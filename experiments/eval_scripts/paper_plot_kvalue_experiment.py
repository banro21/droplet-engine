import numpy as np
import os
import re
import math

import sqlite3
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

db_pattern = re.compile("local_dht_benchmark_kvalue_l(.*)_a(.*)_n(.*)_k(.*).db")
FETCH_CLIENT_DATA = "SELECT time_store_chunk, time_fetch_addr + time_fetch_nonce + time_fetch_chunk " \
                    "FROM CLIENT_STORE_GET " \
                    "WHERE _rowid_>=? AND _rowid_<?;"


def extract_client_data_from_db(db_path, start_data, end_data):
    with sqlite3.connect(db_path) as conn:
        data = np.asarray(conn.execute(FETCH_CLIENT_DATA, (start_data, end_data)).fetchall())
        return data[:, 0], data[:, 1]


def plot_dht_kexperiemnt(num_nodes):
    path = "../data/local_dht_benchmark_kvalue_l10_a3"
    kvalues = [3, 10, 20, 30, 40]

    data_store = []
    data_get = []
    for filename in os.listdir(path):
        if filename.endswith(".db"):
            matching = db_pattern.match(filename)
            if matching:
                num_nodes = int(matching.group(3))
                if num_nodes == num_nodes:
                    kvalue = int(matching.group(4))
                    store_data, get_data = extract_client_data_from_db(os.path.join(path, filename), 25, 1025)
                    data_store.append([kvalue] + store_data.tolist())
                    data_get.append([kvalue] + get_data.tolist())

    data_store = np.asarray(data_store)
    data_get = np.asarray(data_get)

    data_store = data_store[data_store[:, 0].argsort()]
    data_get = data_get[data_get[:, 0].argsort()]

    #########
    # PLOTS #
    #########

    #---------------------------- GLOBAL VARIABLES --------------------------------#
    # figure settings
    fig_width_pt = 300.0                        # Get this from LaTeX using \showthe
    inches_per_pt = 1.0/72.27*2                 # Convert pt to inches
    golden_mean = ((math.sqrt(5)-1.0)/2.0)*.8   # Aesthetic ratio
    fig_width = fig_width_pt*inches_per_pt      # width in inches
    fig_height =(fig_width*golden_mean)           # height in inches
    fig_size = [fig_width,fig_height/1.22]

    params = {'backend': 'ps',
        'axes.labelsize': 18,
        'legend.fontsize': 16,
        'xtick.labelsize': 16,
        'ytick.labelsize': 16,
        'font.size': 16,
        'figure.figsize': fig_size,
        'font.family': 'times new roman'}

    pdf_pages = PdfPages('../plots/paper_plot_kvalue_experiment.pdf')
    fig_size = [fig_width, fig_height / 1.2]

    plt.rcParams.update(params)
    plt.axes([0.12, 0.32, 0.85, 0.63], frameon=True)
    plt.rc('pdf', fonttype=42)  # IMPORTANT to get rid of Type 3

    def compute_avg_std(data):
        return np.median(data, axis=1), np.percentile(data, 95, axis=1)



    f,  ax1 = plt.subplots()

    kvalues = data_store[:, 0]
    mean_s, std_s = compute_avg_std(data_store[:, 1:])
    mean_g, std_g = compute_avg_std(data_get[:, 1:])


    ind = np.arange(1, len(kvalues.tolist())+1)
    width = 0.25

    colours = ['0.3', '0.3', '0.7', '0.7']
    hatch_style='\\\\\\\\'

    ax1.grid(True, linestyle=':', color='0.8', zorder=0, axis='y')
    rects3 = ax1.bar(ind, std_s, width, color=colours[2])  # , yerr=addr_std_s, error_kw=dict(ecolor='0.75', lw=2, capsize=5, capthick=2))
    rects4 = ax1.bar(ind + width, std_g, width, color=colours[3], hatch=hatch_style)  # , yerr=addr_std_g, error_kw=dict(ecolor='0.25', lw=2, capsize=5, capthick=2))
    rects1 = ax1.bar(ind, mean_s, width, color=colours[0]) #yerr=std_s, error_kw=dict(ecolor='0.6', lw=1, capsize=4, capthick=1), zorder=3)
    rects2 = ax1.bar(ind + width, mean_g, width, hatch=hatch_style, color=colours[1]) #yerr=std_g, error_kw=dict(ecolor='0.6', lw=1, capsize=5, capthick=1), zorder=3)


    ax1.set_ylabel("Time [ms]")
    ax1.set_xticks(ind + width)
    ax1.set_xticklabels((map(lambda x: str(int(x)), kvalues.tolist())))
    ax1.set_xlabel("k value")

    #ax1.legend((rects1[0], rects2[0], rects3[0], rects4[0]), ('Store', 'Get', 'Routing Store', 'Routing Get'), loc="upper left", ncol=2)
    ax1.legend((rects1[0], rects2[0],  rects3[0], rects4[0]), ('Median store', 'Median get', '95th precentile store', '95th precentile get'), bbox_to_anchor=(-0.02, 1.00, 1., .102), loc=3, ncol=2, columnspacing=1)

    #handletextpad=0.5, labelspacing=0.2, borderaxespad=0.2, borderpad=0.3)

    #f.suptitle("RTT-%d average latency DHT operations" % latency, fontsize=24, y=1.02)


    F = plt.gcf()
    F.set_size_inches(fig_size)
    pdf_pages.savefig(F, bbox_inches='tight')
    plt.clf()
    pdf_pages.close()

if __name__ == "__main__":
    plot_dht_kexperiemnt(1024)
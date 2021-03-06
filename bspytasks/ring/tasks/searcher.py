import os
import torch
import pickle as p
import matplotlib.pyplot as plt

from bspytasks.ring.tasks.classifier import get_ring_data, ring_task, plot_results
from brainspy.utils.io import (
    load_configs,
    create_directory,
    create_directory_timestamp,
    save,
)

from brainspy.utils.pytorch import TorchUtils


def init_dirs(gap, base_dir, is_main=True):
    main_dir = f"searcher_{gap}mV"
    search_stats_dir = "search_stats"
    results_dir = "results"
    reproducibility_dir = "reproducibility"

    if is_main:
        base_dir = create_directory_timestamp(base_dir, main_dir)
    else:
        base_dir = os.path.join(base_dir, main_dir)
        create_directory(base_dir)
    search_stats_dir = os.path.join(base_dir, search_stats_dir)
    results_dir = os.path.join(base_dir, results_dir)
    reproducibility_dir = os.path.join(base_dir, reproducibility_dir)
    create_directory(search_stats_dir)
    create_directory(results_dir)
    create_directory(reproducibility_dir)
    return base_dir, search_stats_dir, results_dir, reproducibility_dir


def init_results(runs, output_shape):
    results = {}
    results["performance_per_run"] = torch.zeros(runs)
    results["correlation_per_run"] = torch.zeros(runs)
    results["accuracy_per_run"] = torch.zeros(runs)
    results["outputs_per_run"] = torch.zeros((runs, output_shape))
    return results


def init_all_results(dataloaders, runs):
    results = {}
    results["seeds"] = torch.zeros(runs)
    results["train_results"] = init_results(runs, len(dataloaders[0].sampler.indices))
    if len(dataloaders[1]) > 0:
        results["dev_results"] = init_results(runs, len(dataloaders[1].sampler.indices))
    if len(dataloaders[2]) > 0:
        results["test_results"] = init_results(
            runs, len(dataloaders[2].sampler.indices)
        )
    return results


def search_solution(
    configs,
    custom_model,
    criterion,
    algorithm,
    transforms=None,
    logger=None,
    is_main=True,
):
    main_dir, search_stats_dir, results_dir, reproducibility_dir = init_dirs(
        configs["data"]["gap"], configs["results_base_dir"], is_main=is_main
    )
    configs["results_base_dir"] = main_dir
    dataloaders = get_ring_data(configs, transforms)
    all_results = init_all_results(dataloaders, configs["runs"])
    best_run = None

    for run in range(configs["runs"]):
        print(f"########### RUN {run} ################")
        all_results["seeds"][run] = TorchUtils.init_seed(None, deterministic=True)

        results, model = ring_task(
            configs,
            dataloaders,
            custom_model,
            criterion,
            algorithm,
            logger=logger,
            is_main=False,
            save_data=False,
        )
        all_results = update_all_search_stats(all_results, results, run)
        if is_best_run(results, best_run):
            results["best_index"] = run
            best_run = results
            plot_results(results, plots_dir=results_dir)
            torch.save(model, os.path.join(reproducibility_dir, "model.pt"))
            torch.save(
                results,
                os.path.join(reproducibility_dir, "results.pickle"),
                pickle_protocol=p.HIGHEST_PROTOCOL,
            )
            save(
                "configs",
                os.path.join(reproducibility_dir, "configs.yaml"),
                data=configs,
            )
            torch.save(results, os.path.join(search_stats_dir, "best_result.pickle"))

    close_search(
        all_results,
        search_stats_dir,
        "all_results_"
        + str(configs["data"]["gap"])
        + "_gap_"
        + str(configs["runs"])
        + "_runs",
    )


def is_best_run(results, best_run):
    if best_run == None:
        return True
    elif "test_results" in results:
        return (
            results["test_results"]["performance"]
            < best_run["test_results"]["performance"]
        )
    elif "dev_results" in results:
        return (
            results["dev_results"]["performance"]
            < best_run["dev_results"]["performance"]
        )
    else:
        return (
            results["train_results"]["performance"]
            < best_run["train_results"]["performance"]
        )


def update_all_search_stats(all_results, run_results, run):
    all_results["train_results"] = update_search_stats(
        all_results["train_results"], run_results["train_results"], run
    )
    if "dev_results" in run_results:
        all_results["dev_results"] = update_search_stats(
            all_results["dev_results"], run_results["dev_results"], run
        )
    if "test_results" in run_results:
        all_results["test_results"] = update_search_stats(
            all_results["test_results"], run_results["test_results"], run
        )
    return all_results


def update_search_stats(all_results, run_results, run):
    all_results["accuracy_per_run"][run] = run_results["accuracy"]["accuracy_value"]
    all_results["performance_per_run"][run] = run_results["performance"]
    # self.correlation_per_run[run] = results['correlation']
    all_results["outputs_per_run"][run] = run_results["best_output"][:, 0]
    # self.control_voltages_per_run[run] = results['control_voltages']
    return all_results


def close_search(all_results, save_dir, dir_name):
    # inputs_test, targets_test, mask_test = self.data_loader.get_data(self.configs['algorithm_configs']['processor'], gap=gap, istest=True)
    # np.savez(os.path.join(self.search_stats_dir, f"search_data_{self.configs['runs']}_runs.npz"), outputs=self.outputs_per_run, performance=self.performance_per_run, accuracy=self.accuracy_per_run, seed=self.seeds_per_run, control_voltages=self.control_voltages_per_run, inputs_test=inputs_test, targets_test=targets_test, mask_test=mask_test)
    torch.save(all_results, os.path.join(save_dir, dir_name + ".pickle"))
    plot_all_search_results(all_results, save_dir)


def plot_all_search_results(results, save_dir, extension="png"):
    plot_search_results(
        "train", results["train_results"], save_dir, extension=extension
    )
    if "dev_results" in results:
        plot_search_results(
            "dev", results["dev_results"], save_dir, extension=extension
        )
    if "test_results" in results:
        plot_search_results(
            "test", results["test_results"], save_dir, extension=extension
        )


def plot_search_results(label, results, save_dir, extension="png", show_plots=False):
    accuracy_per_run = TorchUtils.get_numpy_from_tensor(results["accuracy_per_run"])
    performance_per_run = TorchUtils.get_numpy_from_tensor(
        results["performance_per_run"]
    )

    plt.figure()
    plt.plot(accuracy_per_run, performance_per_run, "o")
    plt.title("Accuracy vs Fisher (" + label + ")")
    plt.xlabel("Accuracy")
    plt.ylabel("Fisher value")
    plt.savefig(os.path.join(save_dir, "accuracy_vs_fisher_" + label + "." + extension))

    plt.figure()
    plt.hist(performance_per_run, 100)
    plt.title("Histogram of Fisher values (" + label + ")")
    plt.xlabel("Fisher values")
    plt.ylabel("Counts")
    plt.savefig(
        os.path.join(save_dir, "fisher_values_histogram_" + label + "." + extension)
    )

    plt.figure()
    plt.hist(accuracy_per_run, 100)
    plt.title("Histogram of Accuracy values")
    plt.xlabel("Accuracy values")
    plt.ylabel("Counts")
    plt.savefig(os.path.join(save_dir, "accuracy_histogram_" + label + "." + extension))

    if show_plots:
        plt.show()


if __name__ == "__main__":

    from torchvision import transforms

    from brainspy.utils import manager
    from brainspy.utils.io import load_configs
    from brainspy.utils.transforms import DataToTensor, DataToVoltageRange
    from brainspy.processors.dnpu import DNPU

    V_MIN = [-1.2, -1.2]
    V_MAX = [0.6, 0.6]

    transforms = transforms.Compose(
        [DataToVoltageRange(V_MIN, V_MAX, -1, 1), DataToTensor(torch.device('cpu'))]
    )

    configs = load_configs("configs/ring.yaml")

    criterion = manager.get_criterion(configs["algorithm"])
    algorithm = manager.get_algorithm(configs["algorithm"])

    search_solution(configs, DNPU, criterion, algorithm, transforms=transforms)

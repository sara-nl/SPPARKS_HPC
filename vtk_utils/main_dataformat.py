import os
from typing import List, Tuple, Union, Optional, Dict
import numpy as np
import re
from argparse import ArgumentParser
import tarfile
import tempfile

import vtk
import h5py
from vtk_data_utils import (
    read_vtk_instance,
    convert_vtk_instance_to_numpy,
    extract_top_2D_slice_with_voi,
)
from vtk_tar_utils import (
    count_folders_in_tar,
    process_file,
    process_directory,
)


def save_data_to_hdf5(data_list: List[np.ndarray], output_file: str) -> None:
    with h5py.File(output_file, "w") as hdf_file:
        hdf_file.create_dataset("images", data=np.array(data_list))


def extract_vtk_folders_from_tar(
    tar_path: str,
) -> Dict[int, List[List[vtk.vtkImageData]]]:
    """
    Extract and process samples from a compressed TAR file.

    Opens a TAR file, iterates through its contents using a streaming approach to prevent memory overload,
    extracts data and organizes it into a structured format.
    It also tracks the number of samples per 'experiment' or directory.

    Parameters:
    - tar_path: The file path of the compressed TAR (.tar.gz) file to be processed.

    Returns:
    - A dictionary where:
        - each key represents the count of vtk.vtkImageData objects in each directory,
        - each value is a list of lists, each sublist containing vtk.vtkImageData objects from one directory (experiment).
    """
    all_sample = {}
    temporal_sequence = []
    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in iter(lambda: tar.next(), None):
                if member is None:
                    continue
                elif member.isdir():
                    # print("processing directory:", member.name)
                    if temporal_sequence:
                        (temporal_sequence, all_sample) = process_directory(
                            temporal_sequence, all_sample
                        )
                elif member.isfile() and ".vti." in member.name:
                    # print("processing directory:", member.name)
                    n_instance = process_file(member, tar, read_vtk_instance)
                    if n_instance:
                        temporal_sequence.append(n_instance)

        # Process the last sequence after exiting the loop
        if temporal_sequence:
            temporal_sequence, all_sample = process_directory(
                temporal_sequence, all_sample
            )

    except EOFError:
        print("Warning: Reached corrupted section in tar file")
        temporal_sequence, all_sample = process_directory(temporal_sequence, all_sample)
    except tarfile.ReadError:
        print(f"Error reading tar file: {tar_path}")
    except Exception as e:
        print(f"An error occurred while processing the TAR file: {e}")

    return all_sample


def generate_datasets_from_sample_list(
    all_samples: Dict[int, List[List[vtk.vtkImageData]]],
    output_path: str,
    output_name: str,
    slicing: bool = True,
    generate_3D: bool = False,
) -> List[str]:
    """
    Generate and save datasets for each sample count in the all_samples dictionary.

    Parameters:
    - all_samples: A dictionary where keys are sample counts and values are lists of lists of vtkImageData objects.
    - output_path: The directory where HDF5 files will be saved.
    - slicing (bool): If True, 2D datasets are generated by slicing the 3D data.
    - generate_3D (bool): If True, 3D datasets are generated.

    Returns:
      A list of file paths for the saved HDF5 datasets.
    """
    file_paths = []
    for sample_count, data_lists in all_samples.items():
        print(f"{output_name}: len {sample_count} num of experiment: {len(data_lists)}")
        filename = f"{output_name}_len_{sample_count}"
        # Concatenate all sublists in data_lists for this sample_count
        flatten_list = [item for sublist in data_lists for item in sublist]

        datapath_2D, datapath_3D = generate_datasets(
            flatten_list, output_path, filename, slicing, generate_3D
        )
        if datapath_2D:
            file_paths.append(datapath_2D)
        if datapath_3D:
            file_paths.append(datapath_3D)

    return file_paths


def generate_datasets(
    data_list: List[vtk.vtkImageData],
    output_path: str,
    output_name: str,
    slicing: bool = True,
    generate_3D: bool = False,
) -> str:
    """
    Generate the datasets in a suitable format (hdf5) for ML training.
    Before saving it to hdf5, vtk objects are converted to numpy arrays.

    Parameters:
    - data_list: A list of lists containing vtkImageData objects.
    - slicing (bool): If set to True, a 2D dataset is generated by slicing the 3D data.
    - generate_3D (bool): by default is False, if True, a #D dataset is generated.

    Returns:
      File paths of the saved 3D and 2D HDF5 datasets.

    """
    # before saving it to hdf5, vtk objects should be converted to numpy arrays.
    images_3D_list = []
    images_2D_list = []
    for vtkimage in data_list:
        if generate_3D:
            images_3D_list.append(
                convert_vtk_instance_to_numpy(vtkimage, slicing=False)
            )

        if slicing:
            vtkimage_2D = extract_top_2D_slice_with_voi(vtkimage)
            images_2D_list.append(
                convert_vtk_instance_to_numpy(vtkimage_2D, slicing=True)
            )

    # save to hd5f format
    datapath_3D = None
    if generate_3D:
        datapath_3D = os.path.join(output_path, f"{output_name}_3D.h5")
        save_data_to_hdf5(images_3D_list, datapath_3D)

    datapath_2D = None
    if slicing:
        datapath_2D = os.path.join(output_path, f"{output_name}_2D.h5")
        save_data_to_hdf5(images_2D_list, datapath_2D)

    return datapath_2D, datapath_3D


def main(args):
    tar_path = args.tar_path
    output_path = args.output_path
    output_name = args.output_name

    print("processing tar file: ", tar_path)

    # Run this line if you want to get information about the folder saved in the tar:
    # The function:
    # - Returns the number of folders saved in the tar
    # - Write the name of the folder (case name) in a metadata file
    # n = count_folders_in_tar(tar_path, output_path, config_file = f"metadata_{output_name}")
    # print("number of samples in tar is: ", n)

    # Extract the samples from tar
    sample_list = extract_vtk_folders_from_tar(tar_path)

    # generate 2D / 3D datasets
    dataset_2D = generate_datasets_from_sample_list(
        sample_list, output_path, output_name, slicing=True
    )
    print("2D dataset saved in: ", dataset_2D)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--tar_path",
        type=str,
        default="/home/monicar/prjsp/exp_1.tar.gz",
    )
    parser.add_argument(
        "--output_path", type=str, default="/home/monicar/prjsp/configs_tar"
    )
    parser.add_argument("--output_name", type=str, default="exp_1")
    args = parser.parse_args()
    main(args)

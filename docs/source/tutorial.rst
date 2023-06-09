========
Tutorial
========

Overview
--------

Welcome to our data-driven project! In this tutorial, we will walk you through the steps to create and process a satellite dataset using the Cookiecutter architecture, and then run a parameter sweep using the Weights & Biases (wandb) platform.


.. warning::
    .. line-block::
        Make sure you have installed all dependencies and have created a wandb account.
        See :doc:`Installation Guide </install>` for futher informations.


Get Started |project_name|
--------------------------

Navigate to the project directory in your terminal.

Create satellite data
=====================

- Run the `make_data.py` script to generate the satellite dataset (datasets has already been generated).

.. code-block:: bash

    make data

Preprocess data
===============

- After generating the dataset, run the `make_preprocessing.py` script to preprocess and analyze the data.

.. code-block:: bash

    make preprocess

Train the model
===============

- You can now train the model with the configuration available at the end of the file `make_train.py`.

.. code-block:: bash
    
    make train

Creating a Wandb Sweep
======================

- Next, create a Weights & Biases (wandb) sweep to perform a parameter search for model training. A sweep is a set of hyperparameters and their possible values that wandb uses to launch multiple runs with different configurations.

- Open the `sweep.yml` file provided in the project repository, and specify the hyperparameters and their ranges or values for the sweep.

- Save the `sweep.yml` file.

Running the Sweep
=================

- Once the sweep configuration is set, you can run the sweep using the `wandb sweep` command in your terminal, specifying the path to the `sweep.yml` file.

.. code-block:: bash
   
    wandb sweep --project crop-forecasting sweep.yaml

- This will generate a sweep ID, which you can use to launch the sweep runs.

- Run the sweep using the `wandb agent` command, specifying the sweep ID.

.. code-block:: bash
   
        wandb agent <ORG_NAME>/crop-forecasting/<SWEEP_ID>

- The agent will start running the sweep runs with different hyperparameter configurations, and wandb will log the results for each run.

Bonus - Machine Learning
========================

- Use the sweep.yml located in src/models/ml.

- Adapt the path to the configuration file:

.. code-block:: bash
   
    wandb sweep --project crop_forecasting src/models/ml/sweep.yaml

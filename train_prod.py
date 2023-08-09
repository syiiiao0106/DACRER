""" Trains a product extraction or role labeling model on a dataset.
"""

import warnings
warnings.filterwarnings("ignore")
import argparse
import sys
import os

os.environ["WANDB_DISABLED"] = 'false'

if __name__ == '__main__':

    from chemrxnextractor.prod_args import parse_train_args
    from chemrxnextractor.train import prod_train
    args = parse_train_args(['configs/prod_train.json'])
    prod_train(*args)
    
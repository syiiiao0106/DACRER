import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from tqdm.auto import tqdm, trange

import scipy.io as scio
from seqeval.metrics import f1_score, precision_score, accuracy_score,  recall_score, performance_measure, classification_report
import numpy as np
import torch
# from torch import nn   #神经网络
from torch.utils.data.dataset import Dataset
from torch.utils.data import DataLoader
from torch.utils.data.sampler import SequentialSampler

from transformers import AutoConfig, AutoTokenizer
from transformers.data.data_collator import default_data_collator
from transformers import set_seed

from .trainer import IETrainer as Trainer
from chemrxnextractor.models.model import BertForRoleLabeling, BertCRFForRoleLabeling
from chemrxnextractor.models import BertDNNForRoleLabeling
from chemrxnextractor.data import RoleDataset, PlainRoleDataset
from chemrxnextractor.data.utils import get_labels
from chemrxnextractor.constants import PROD_START_MARKER, PROD_END_MARKER
from chemrxnextractor.data.role import write_predictions
from chemrxnextractor.utils import create_logger


logger = logging.getLogger(__name__)
SPECIAL_TOKENS = [PROD_START_MARKER, PROD_END_MARKER]


def train(model_args, data_args, train_args):
    if (
        os.path.exists(train_args.output_dir)
        and os.listdir(train_args.output_dir)
        and train_args.do_train
        and not train_args.overwrite_output_dir
    ):
        raise ValueError(
            f"Output directory ({train_args.output_dir}) already exists and is not empty."
            " Use --overwrite_output_dir to overcome."
        )

    # Setup logging
    logging.basicConfig(
        format="%(asctime)s - %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
        level=logging.INFO if train_args.local_rank in [-1, 0] else logging.WARN,
    )
    # logger = create_logger(name="train_role", save_dir=train_args.output_dir)
    logger.info("Training/evaluation parameters %s", train_args)

    # Set seed
    set_seed(train_args.seed)

    labels = get_labels(data_args.labels)
    label_map: Dict[int, str] = {i: label for i, label in enumerate(labels)} #0-17
    num_labels = len(labels) #17种

    config = AutoConfig.from_pretrained(
        model_args.model_name_or_path,
        num_labels=num_labels,
        id2label=label_map,
        label2id={label: i for i, label in enumerate(labels)},
        cache_dir=model_args.cache_dir,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        model_args.model_name_or_path,
        cache_dir=model_args.cache_dir,
        use_fast=model_args.use_fast,
        additional_special_tokens=SPECIAL_TOKENS
    )
    if model_args.use_crf:
        model = BertCRFForRoleLabeling.from_pretrained(
            model_args.model_name_or_path,
            config=config,
            cache_dir=model_args.cache_dir,
            tagging_schema="BIO",
            use_cls=model_args.use_cls,
            prod_pooler=model_args.prod_pooler
        )
    else:
        model = BertDNNForRoleLabeling.from_pretrained(
            model_args.model_name_or_path,
            config=config,
            cache_dir=model_args.cache_dir,
            use_cls=model_args.use_cls,
            prod_pooler=model_args.prod_pooler
        )
    model.resize_token_embeddings(len(tokenizer))
    

    # Get datasets
    train_dataset = (
        RoleDataset(
            data_file=os.path.join(data_args.data_dir, "train.txt"),
            tokenizer=tokenizer,
            labels=labels,
            model_type=config.model_type,
            max_seq_length=data_args.max_seq_length,
            overwrite_cache=data_args.overwrite_cache
        )
        if train_args.do_train
        else None
    )
    eval_dataset = (
        RoleDataset(
            data_file=os.path.join(data_args.data_dir, "dev.txt"),
            tokenizer=tokenizer,
            labels=labels,
            model_type=config.model_type,
            max_seq_length=data_args.max_seq_length,
            overwrite_cache=data_args.overwrite_cache
        )
        if train_args.do_eval
        else None
    )

    def compute_metrics(predictions, label_ids) -> Dict:
        label_list = [[label_map[x] for x in seq] for seq in label_ids]
        preds_list = [[label_map[x] for x in seq] for seq in predictions]
     
        return {
            "precision": precision_score(label_list, preds_list),
            "acc": accuracy_score(label_list, preds_list),
            "recall": recall_score(label_list, preds_list),
            "f1": f1_score(label_list, preds_list),
            "performance_measure": performance_measure(label_list, preds_list),
            "classification report": classification_report(label_list, preds_list),
            # "label_list": scio.savemat('label_list.mat', mdict={'label_list': label_ids}),
            # "preds_list": scio.savemat('preds_list.mat', mdict={'preds_list': predictions}),
        }
        
    metrics_fn = compute_metrics

    # Initialize our Trainer
    trainer = Trainer(
        model=model,
        args=train_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        compute_metrics=metrics_fn,
        use_crf=model_args.use_crf
    )

    # Training 
    if train_args.do_train:
        trainer.train()
        # Pass model_path to train() if continue training from an existing ckpt.
        # trainer.train(
        #     model_path=model_args.model_name_or_path
        #     if os.path.isdir(model_args.model_name_or_path)
        #     else None
        # )
        trainer.save_model()
        tokenizer.save_pretrained(train_args.output_dir)

    # Evaluation  
    if train_args.do_eval:
        logger.info("*** Evaluate ***")

        output = trainer.evaluate()
        predictions = output['predictions'] 
        label_ids = output['label_ids']
        metrics = output["metrics"] 

        output_eval_file = os.path.join(train_args.output_dir, "eval_results.txt")
        with open(output_eval_file, "w") as writer:
            logger.info("***** Eval results *****")
            for key, value in metrics.items():
                logger.info("  %s = %s", key, value)
                writer.write("%s = %s\n" % (key, value))

        preds_list = [[label_map[x] for x in seq] for seq in predictions] 

        # Save predictions 
        write_predictions(
            os.path.join(data_args.data_dir, "dev.txt"),
            os.path.join(train_args.output_dir, "eval_predictions.txt"),
            preds_list
        )

    # Predict 
    if train_args.do_predict:
        test_dataset = RoleDataset(
            data_file=os.path.join(data_args.data_dir, "test.txt"),
            tokenizer=tokenizer,
            labels=labels,
            model_type=config.model_type,
            max_seq_length=data_args.max_seq_length,
            overwrite_cache=data_args.overwrite_cache
        )

        output = trainer.predict(test_dataset)
        predictions = output['predictions']
        label_ids = output['label_ids']
        metrics = output["metrics"]
        # Note: preds_list doesn't contain labels for [Prod] and [/Prod]
        preds_list = [[label_map[x] for x in seq] for seq in predictions]

        output_test_results_file = os.path.join(train_args.output_dir, "test_results.txt")
        with open(output_test_results_file, "w") as writer:
            for key, value in metrics.items():
                logger.info("  %s = %s", key, value)
                writer.write("%s = %s\n" % (key, value))

        # Save predictions
        write_predictions(
            os.path.join(data_args.data_dir, "test.txt"),
            os.path.join(train_args.output_dir, "test_predictions.txt"),
            preds_list
        )


def predict(model_args, predict_args):
    # Setup logging
    logging.basicConfig(
        format="%(asctime)s - %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
        level=logging.INFO,
    )

    # logger = create_logger(name="predict_role", save_dir=train_args.output_dir)
    logger.info("Predict parameters %s", predict_args)

    # Prepare prod-ext task
    labels = get_labels(predict_args.labels)
    label_map: Dict[int, str] = {i: label for i, label in enumerate(labels)}
    num_labels = len(labels)

    # Load pretrained model and tokenizer
    config = AutoConfig.from_pretrained(
        model_args.model_name_or_path,
        num_labels=num_labels,
        id2label=label_map,
        label2id={label: i for i, label in enumerate(labels)},
        cache_dir=model_args.cache_dir,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        model_args.model_name_or_path,
        cache_dir=model_args.cache_dir,
        use_fast=model_args.use_fast,
        additional_special_tokens=SPECIAL_TOKENS
    )
    if model_args.use_crf:
        model = BertCRFForRoleLabeling.from_pretrained(
            model_args.model_name_or_path,
            config=config,
            cache_dir=model_args.cache_dir,
            tagging_schema="BIO",
            use_cls=model_args.use_cls,
            prod_pooler=model_args.prod_pooler,
        )
    else:
        model = BertDNNForRoleLabeling.from_pretrained(
            model_args.model_name_or_path,
            config=config,
            cache_dir=model_args.cache_dir,
            use_cls=model_args.use_cls,
            prod_pooler=model_args.prod_pooler,
        )

    device = torch.device(
                "cuda"
                if (not predict_args.no_cuda and torch.cuda.is_available())
                else "cpu"
            )
    model = model.to(device)


    # load test dataset
    test_dataset = PlainRoleDataset(
        data_file=predict_args.input_file,
        tokenizer=tokenizer,
        labels=labels,
        model_type=config.model_type,
        max_seq_length=predict_args.max_seq_length,
        overwrite_cache=predict_args.overwrite_cache,
    )

    sampler = SequentialSampler(test_dataset)
    data_loader = DataLoader(
        test_dataset,
        sampler=sampler,
        batch_size=predict_args.batch_size,
        collate_fn=default_data_collator
    )

    logger.info("***** Running Prediction *****")
    logger.info("  Num examples = %d", len(data_loader.dataset))
    logger.info("  Batch size = %d", predict_args.batch_size)

    model.eval()

    with open(predict_args.input_file, "r") as f:
        all_preds = []
        for inputs in tqdm(data_loader, desc="Predicting"):
            for k, v in inputs.items():
                if isinstance(v, torch.Tensor):
                    inputs[k] = v.to(device)
            with torch.no_grad():
                outputs = model(
                    input_ids=inputs['input_ids'],
                    attention_mask=inputs['attention_mask'],
                    prod_start_mask=inputs['prod_start_mask'],
                    prod_end_mask=inputs['prod_end_mask'],
                    prod_mask=inputs['prod_mask'],
                    token_type_ids=inputs['token_type_ids']
                )
                logits = outputs[0]

            preds = model.decode(logits, mask=inputs['decoder_mask'].bool())
            preds_list = [[label_map[x] for x in seq] for seq in preds]

            all_preds += preds_list

    write_predictions(
        predict_args.input_file,
        predict_args.output_file,
        all_preds,
        align="plain"
    )


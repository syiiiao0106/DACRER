# DACRER: A Transformer-Based Chemical Reaction Entity Recognition Method
This repository contains code/data for the paper "DACRER:A Transformer-Based Chemical Reaction Entity Recognition Method Driven by Natural Language Data Augmentation Strategy."

## Installation
1.Pre-requirements
```
- pytorch==1.12
- transformers==3.0.2
- numpy
- seqeval
- scilit-learn
```
2.Clone this repo
`git clone https://github.com/syiiiao0106/DACRER.git`

## Data preprocessing
We provide the annotated data after labeling and tenfold augmentation in `/tests`.

## Model training and testing
* To trained a new model, we download ChemBERT model via path [chembert_cased](https://huggingface.co/jiangg/chembert_cased). 
* Run `$ train.py` to perform training and model evalution using our annotated data `tests/data/role`.
* Run `$ train_prod.py` to perform validation using another annotated dataset `tests/data/prod`.
* We provided codes to train models using the provided data or your own dataset.

## Performance
Performance of the provided models on our annotated data:
Precision|Recall|F1|Accuracy
:-:|:-:|:-:|:-:
77.3|85.0|81.0|96.1
 

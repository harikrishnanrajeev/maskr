from os.path import join, expanduser
import torch
from fastai import *
from maskr.models.maskrcnn import MaskRCNN
from maskr.callbacks import *
from maskr.samples.nuke.dataset import Dataset

ROOT_DIR = "/home/ubuntu/maskr"
DATA = join(expanduser("~"), "data", "nuke")

def get_data(config):
    " return a databunch based on config"

    # define samples
    pvalid = .2
    trainpath = join(DATA, "stage1_train")
    df = pd.DataFrame(os.listdir(trainpath), columns=["image"])
    train = np.random.random(len(df))>pvalid
    df.loc[train, "subset"] = "train"
    df.loc[~train, "subset"] = "valid"
    df.to_pickle(join(DATA, "subset.pkl"))
    log.info(df.subset.value_counts())

    # load datasets
    train_ds = Dataset(config)
    train_ds.load_nuke(trainpath, "train")
    train_ds.prepare()
    val_ds = Dataset(config)
    val_ds.load_nuke(trainpath, "valid")
    val_ds.prepare()

    # define dataloaders
    train_gen = torch.utils.data.DataLoader(train_ds, batch_size=config.BATCH_SIZE,
                                            shuffle=config.SHUFFLE, num_workers=config.WORKERS)
    val_gen = torch.utils.data.DataLoader(val_ds, batch_size=config.BATCH_SIZE, num_workers=config.WORKERS)
    data = DataBunch(train_gen, val_gen, device=config.DEVICE)

    return data

def get_model(config):
    " return a model based on config "

    # define model
    model = MaskRCNN(config=config)
    model.initialize_weights()
    model.to(config.DEVICE)

    # load pretrained except final layers that depend on NUM_CLASSES
    params = torch.load(config.WEIGHTS)
    params.pop('classifier.linear_class.weight')
    params.pop("classifier.linear_bbox.weight")
    params.pop("mask.conv5.weight")
    params.pop('classifier.linear_class.bias')
    params.pop("classifier.linear_bbox.bias")
    params.pop("mask.conv5.bias")
    model.load_state_dict(params, strict=False)

    # define training layers
    layer_regex = {
        # all layers but the backbone
        "heads": r"(fpn.P5\_.*)|(fpn.P4\_.*)|(fpn.P3\_.*)|(fpn.P2\_.*)|(rpn.*)|(classifier.*)|(mask.*)",
        # From a specific Resnet stage and up
        "3+": r"(fpn.C3.*)|(fpn.C4.*)|(fpn.C5.*)|(fpn.P5\_.*)|(fpn.P4\_.*)|(fpn.P3\_.*)|(fpn.P2\_.*)|(rpn.*)|(classifier.*)|(mask.*)",
        "4+": r"(fpn.C4.*)|(fpn.C5.*)|(fpn.P5\_.*)|(fpn.P4\_.*)|(fpn.P3\_.*)|(fpn.P2\_.*)|(rpn.*)|(classifier.*)|(mask.*)",
        "5+": r"(fpn.C5.*)|(fpn.P5\_.*)|(fpn.P4\_.*)|(fpn.P3\_.*)|(fpn.P2\_.*)|(rpn.*)|(classifier.*)|(mask.*)",
        # All layers
        "all": ".*",
    }
    layers = layer_regex["heads"]
    model.set_trainable(layers)

    return model

def get_learn(config):
    data = get_data(config)
    model = get_model(config)

    # add callbacks
    callback_fns = [Multiloss, BnFreeze, partial(GradientClipping, clip=5), ShowGraph, TrainSave]
    if config.DEVICE=="cuda":
        callback_fns.append(Cuda)
    if config.COMPAT:
        callback_fns.append(StrictBnFreeze)

    # define optimizer
    opt_func = partial(torch.optim.SGD, momentum=model.config.LEARNING_MOMENTUM)

    learn = Learner(data, model, callback_fns=callback_fns, loss_func=lambda x, *y: x, opt_func=opt_func)
    return learn